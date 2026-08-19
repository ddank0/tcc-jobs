"""Casca do treino: lê serie_mensal, chama o núcleo puro, grava o resultado.

Acionada só pela CLI - nunca por HTTP. A API lê as tabelas que este módulo
escreve.
"""

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import polars as pl
from sqlalchemy import Engine, delete, text
from sqlalchemy.orm import Session

from tcc_jobs.core.competencia import Competencia
from tcc_jobs.db.copiador import copiar_para_tabela
from tcc_jobs.db.models import ExecucaoModelo, Previsao
from tcc_jobs.db.session import criar_sessionmaker
from tcc_jobs.etl.armazenamento import Armazenamento
from tcc_jobs.ml.anomaly import contribuicoes, pontuar
from tcc_jobs.ml.features import CHAVE, COLUNAS_FEATURES, montar_features
from tcc_jobs.ml.forecast import (
    NIVEL_INTERVALO,
    Selecao,
    SerieTemporal,
    prever,
    selecionar_series,
)

logger = logging.getLogger(__name__)

AGRUPAMENTOS = ("orgao", "modalidade", "global")

# Dois ciclos anuais: menos que isso o componente sazonal não é estimável.
MINIMO_TREINO = 24


@dataclass(frozen=True)
class ResultadoTreino:
    series_treinadas: int
    series_descartadas: int
    previsoes_gravadas: int


def _consulta(agrupamento: str) -> str:
    """A série é reagregada conforme o agrupamento pedido.

    serie_mensal é por (orgao, modalidade); treinar por órgão soma as
    modalidades. As colunas placeholder mantêm o contrato de selecionar_series.
    """
    if agrupamento == "orgao":
        return """
            SELECT competencia, codigo_orgao, 0 AS codigo_modalidade,
                   sum(quantidade_licitacoes) AS quantidade_licitacoes,
                   sum(valor_total) AS valor_total
            FROM serie_mensal GROUP BY 1, 2
        """
    if agrupamento == "modalidade":
        return """
            SELECT competencia, '' AS codigo_orgao, codigo_modalidade,
                   sum(quantidade_licitacoes) AS quantidade_licitacoes,
                   sum(valor_total) AS valor_total
            FROM serie_mensal GROUP BY 1, 3
        """
    return """
        SELECT competencia, '' AS codigo_orgao, 0 AS codigo_modalidade,
               sum(quantidade_licitacoes) AS quantidade_licitacoes,
               sum(valor_total) AS valor_total
        FROM serie_mensal GROUP BY 1
    """


def _chave(agrupamento: str, serie: SerieTemporal) -> str:
    """Formato documentado no modelo: orgao:22000, modalidade:5, global."""
    if agrupamento == "orgao":
        return f"orgao:{serie.codigo_orgao}"
    if agrupamento == "modalidade":
        return f"modalidade:{serie.codigo_modalidade}"
    return "global"


def treinar(engine: Engine, agrupamento: str, h: int = 12) -> ResultadoTreino:
    """Treina AutoARIMA por série e grava previsões com intervalo.

    Idempotente por agrupamento: a rodada anterior sai antes de a nova entrar,
    e o CASCADE da FK leva as previsões junto.
    """
    if agrupamento not in AGRUPAMENTOS:
        raise ValueError(f"agrupamento deve ser um de {AGRUPAMENTOS}, veio {agrupamento!r}")

    with engine.begin() as conn:
        df = pl.read_database(_consulta(agrupamento), connection=conn)

    inicio = time.perf_counter()
    selecao: Selecao = selecionar_series(df.lazy(), minimo_treino=MINIMO_TREINO, h=h)

    linhas: list[dict[str, object]] = []
    for serie in selecao.series:
        proximas = _proximas_competencias(serie.competencias[-1], h)
        for alvo, valores in (("quantidade", serie.quantidades), ("valor", serie.valores)):
            previsao = prever(valores, h=h)
            linhas.extend(
                {
                    "serie_chave": _chave(agrupamento, serie),
                    "competencia_alvo": c,
                    "alvo": alvo,
                    "valor_previsto": p,
                    "ic_inferior": b,
                    "ic_superior": a,
                }
                for c, p, b, a in zip(
                    proximas,
                    previsao.pontual,
                    previsao.inferior,
                    previsao.superior,
                    strict=True,
                )
            )

    duracao = time.perf_counter() - inicio
    total = _persistir(engine, agrupamento, h, selecao, linhas, duracao, df)

    logger.info(
        "train %s: %d séries, %d descartadas, %d previsões em %.1fs",
        agrupamento,
        selecao.elegiveis,
        selecao.descartadas,
        total,
        duracao,
    )
    return ResultadoTreino(
        series_treinadas=selecao.elegiveis,
        series_descartadas=selecao.descartadas,
        previsoes_gravadas=total,
    )


def _proximas_competencias(ultima: str, h: int) -> list[str]:
    atual = Competencia.de_str(ultima)
    saida: list[str] = []
    for _ in range(h):
        atual = atual.proxima()
        saida.append(str(atual))
    return saida


def _persistir(
    engine: Engine,
    agrupamento: str,
    h: int,
    selecao: Selecao,
    linhas: list[dict[str, object]],
    duracao: float,
    df: pl.DataFrame,
) -> int:
    tipo = f"forecast:{agrupamento}"

    with criar_sessionmaker(engine)() as sessao:
        _remover_rodada_anterior(sessao, tipo)

        execucao = ExecucaoModelo(
            tipo=tipo,
            algoritmo="AutoARIMA",
            parametros_json={
                "season_length": 12,
                "horizonte": h,
                "minimo_treino": MINIMO_TREINO,
                "nivel_intervalo": NIVEL_INTERVALO,
            },
            metricas_json={
                "series_treinadas": selecao.elegiveis,
                "series_descartadas": selecao.descartadas,
                "duracao_segundos": round(duracao, 1),
            },
            janela_treino_inicio=str(df["competencia"].min()) if df.height else None,
            janela_treino_fim=str(df["competencia"].max()) if df.height else None,
            executado_em=datetime.now(UTC).replace(tzinfo=None),
        )
        sessao.add(execucao)
        sessao.flush()

        for linha in linhas:
            sessao.add(Previsao(execucao_id=execucao.id, **linha))  # type: ignore[arg-type]

        sessao.commit()
        return len(linhas)


def _remover_rodada_anterior(sessao: Session, tipo: str) -> None:
    """A execução anterior do mesmo tipo sai; o CASCADE leva as previsões.

    A tabela guarda estado corrente, não histórico: manter só a rodada vigente
    é o que deixa a API ler `previsao` sem filtrar por execução. O histórico
    de comparações entre configurações vive no relatório do backtesting.
    """
    ids = (
        sessao.execute(text("SELECT id FROM execucao_modelo WHERE tipo = :t"), {"t": tipo})
        .scalars()
        .all()
    )
    if ids:
        sessao.execute(delete(Previsao).where(Previsao.execucao_id.in_(ids)))
        sessao.execute(delete(ExecucaoModelo).where(ExecucaoModelo.id.in_(ids)))


@dataclass(frozen=True)
class ResultadoScore:
    pontuadas: int


def pontuar_universo(
    engine: Engine, armazenamento: Armazenamento, seed: int = 42
) -> ResultadoScore:
    """Monta a matriz do silver, pontua e grava score_anomalia.

    A matriz vem do silver (74,8M de participantes agregados em ~13s), mas o
    licitacao_id vem do banco - o silver não o conhece, porque é o banco que o
    gera. O join é pela chave natural.

    Nulos viram neutros aqui, na casca, com a decisão explícita: razão sem
    referência vira 1 (típico), taxa sem vencedor vira 0. O detector recusa
    nulo de propósito para essa decisão nunca ser implícita.
    """
    lic = pl.scan_parquet(f"{armazenamento.silver}/licitacao/*.parquet")
    itens = pl.scan_parquet(f"{armazenamento.silver}/item/*.parquet")
    part = pl.scan_parquet(f"{armazenamento.silver}/participante/*.parquet")

    matriz = montar_features(lic, itens, part).collect()
    if matriz.height == 0:
        logger.warning("score: nenhum dado em silver")
        return ResultadoScore(pontuadas=0)

    neutros = {
        "razao_valor_grupo": 1.0,
        "razao_participantes_modalidade": 1.0,
        "taxa_vitoria_vencedor": 0.0,
        "razao_item_max": 1.0,
        "desvio_sazonal_orgao": 1.0,
        "hhi_orgao": 0.0,
    }
    matriz = matriz.with_columns([pl.col(c).fill_null(v) for c, v in neutros.items()]).with_columns(
        pl.col("sem_vencedor").cast(pl.Float64), pl.col("contem_item_implausivel").cast(pl.Float64)
    )

    so_features = matriz.select(COLUNAS_FEATURES)
    scores = pontuar(so_features, seed=seed)
    contribs = contribuicoes(so_features)

    with engine.begin() as conn:
        ids = pl.read_database(
            "SELECT id, numero_licitacao, codigo_ug, codigo_modalidade FROM licitacao",
            connection=conn,
        )
    com_id = matriz.with_columns(pl.Series("score", scores.valores)).join(
        ids.with_columns(pl.col("codigo_modalidade").cast(pl.Int64)),
        left_on=CHAVE,
        right_on=["numero_licitacao", "codigo_ug", "codigo_modalidade"],
        how="inner",
    )

    ordenado = com_id.sort("score", descending=True).with_row_index("posicao", offset=1)

    total = _persistir_scores(engine, ordenado, contribs, matriz, seed)
    logger.info("score: %d licitações pontuadas", total)
    return ResultadoScore(pontuadas=total)


def _persistir_scores(
    engine: Engine,
    ordenado: pl.DataFrame,
    contribs: list[list[tuple[str, float]]],
    matriz: pl.DataFrame,
    seed: int,
) -> int:
    """Grava via COPY, não ORM: são 1,74 milhão de linhas.

    A primeira versão usava sessao.add por linha e levou 9,9 min - dentro do
    orçamento por seis segundos, mas violando a regra do projeto, e o score é
    o job que mais se repete. O features_json é montado como texto por
    compreensão única; o gargalo era o round-trip por linha do ORM, não a
    serialização.
    """
    import json

    matriz_idx = matriz.with_row_index("idx_original")
    ordenado = ordenado.join(
        matriz_idx.select(CHAVE + ["idx_original"]),
        left_on=CHAVE,
        right_on=CHAVE,
        how="left",
    )

    tipo = "anomaly:licitacao"
    with engine.begin() as conn:
        antigos = (
            conn.execute(text("SELECT id FROM execucao_modelo WHERE tipo = :t"), {"t": tipo})
            .scalars()
            .all()
        )
        for antigo in antigos:
            # o CASCADE da FK leva os scores
            conn.execute(text("DELETE FROM execucao_modelo WHERE id = :i"), {"i": antigo})

    with criar_sessionmaker(engine)() as sessao:
        execucao = ExecucaoModelo(
            tipo=tipo,
            algoritmo="IsolationForest",
            parametros_json={"n_estimators": 100, "seed": seed, "normalizacao": "mediana/IQR"},
            metricas_json={"pontuadas": ordenado.height},
            janela_treino_inicio=None,
            janela_treino_fim=None,
            executado_em=datetime.now(UTC).replace(tzinfo=None),
        )
        sessao.add(execucao)
        sessao.commit()
        execucao_id = execucao.id

    valores_cols = ordenado.select(COLUNAS_FEATURES).to_dicts()
    indices = ordenado["idx_original"].to_list()
    features_json = [
        json.dumps(
            {
                "valores": valores_cols[i],
                "contribuicoes": [
                    {"atributo": nome, "desvio": round(v, 4)}
                    for nome, v in contribs[int(indices[i])][:5]
                ],
            }
        )
        for i in range(ordenado.height)
    ]

    para_copiar = ordenado.select(
        pl.lit(execucao_id).alias("execucao_id"),
        pl.col("id").alias("licitacao_id"),
        pl.col("score").round(6),
        pl.col("posicao").alias("posicao_ranking"),
    ).with_columns(pl.Series("features_json", features_json))

    with engine.begin() as conn:
        total = copiar_para_tabela(
            conn,
            "score_anomalia",
            para_copiar,
            ["execucao_id", "licitacao_id", "score", "posicao_ranking", "features_json"],
        )
    return total
