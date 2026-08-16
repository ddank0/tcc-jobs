"""Carga de silver para o PostgreSQL.

Casca imperativa. A idempotência é o requisito central: reprocessar a mesma
competência não pode duplicar registros.

COPY não suporta ON CONFLICT, e é o COPY que dá a velocidade - 17x mais rápido
que ORM. A conciliação é carregar numa tabela temporária e depois fazer
INSERT ... ON CONFLICT a partir dela.
"""

import logging
from dataclasses import dataclass, field

import polars as pl
from sqlalchemy import Connection, Engine, text

from tcc_jobs.core.competencia import Competencia
from tcc_jobs.db.copiador import copiar_para_tabela
from tcc_jobs.etl.armazenamento import Armazenamento

logger = logging.getLogger(__name__)

CHAVE_NATURAL = ["numero_licitacao", "codigo_ug", "codigo_modalidade"]

COLUNAS_ITEM = [
    "codigo_item_compra",
    "descricao",
    "quantidade",
    "valor_item",
    "cnpj_vencedor",
]

COLUNAS_PARTICIPANTE = [
    "codigo_item_compra",
    "cnpj_participante",
    "flag_vencedor",
]

COLUNAS_LICITACAO = [
    "numero_licitacao",
    "codigo_ug",
    "codigo_modalidade",
    "numero_processo",
    "objeto",
    "situacao",
    "data_abertura",
    "data_resultado",
    "valor",
    "competencia",
]


@dataclass
class ResultadoCarga:
    competencia: Competencia
    inseridas: dict[str, int] = field(default_factory=dict)
    erro: str | None = None


def carregar(
    competencias: list[Competencia],
    armazenamento: Armazenamento,
    engine: Engine,
) -> list[ResultadoCarga]:
    """Carrega silver no PostgreSQL, uma competência por transação."""
    return [_carregar_uma(c, armazenamento, engine) for c in competencias]


def _ler_silver(armazenamento: Armazenamento, c: Competencia, tabela: str) -> pl.DataFrame:
    caminho = armazenamento.caminho_silver(c, tabela)
    return pl.read_parquet(caminho) if caminho.exists() else pl.DataFrame()


def _carregar_uma(
    competencia: Competencia, armazenamento: Armazenamento, engine: Engine
) -> ResultadoCarga:
    resultado = ResultadoCarga(competencia=competencia)

    try:
        lic = _ler_silver(armazenamento, competencia, "licitacao")
        item = _ler_silver(armazenamento, competencia, "item")
        part = _ler_silver(armazenamento, competencia, "participante")

        if lic.height == 0:
            resultado.erro = "silver ausente ou vazio - rode ingest primeiro"
            return resultado

        with engine.begin() as conn:
            # A ordem importa: modalidade e as dimensões antes de licitacao,
            # que tem FK para elas.
            resultado.inseridas["modalidade"] = _carregar_modalidades(conn, lic)
            resultado.inseridas["orgao"] = _carregar_orgaos(conn, lic)
            resultado.inseridas["unidade_gestora"] = _carregar_ugs(conn, lic)
            resultado.inseridas["fornecedor"] = _carregar_fornecedores(conn, item, part)
            resultado.inseridas["licitacao"] = _carregar_licitacoes(conn, lic)
            resultado.inseridas["item"] = _carregar_filhos(
                conn, item, "item_licitacao", COLUNAS_ITEM
            )
            resultado.inseridas["participante"] = _carregar_filhos(
                conn, part, "participante_licitacao", COLUNAS_PARTICIPANTE
            )

        logger.info("load %s: %s", competencia, resultado.inseridas)

    except Exception as erro:  # noqa: BLE001 - uma competência ruim não derruba o lote
        resultado.erro = f"{type(erro).__name__}: {erro}"
        logger.exception("load %s falhou", competencia)

    return resultado


def _via_temporaria(
    conn: Connection,
    df: pl.DataFrame,
    tabela: str,
    colunas: list[str],
    conflito: list[str],
    atualizar: list[str],
) -> int:
    """COPY para tabela temporária, depois INSERT ... ON CONFLICT."""
    if df.height == 0:
        return 0

    temp = f"tmp_{tabela}"
    lista = ", ".join(f'"{c}"' for c in colunas)
    atribuicoes = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in atualizar)
    acao = f"DO UPDATE SET {atribuicoes}" if atribuicoes else "DO NOTHING"
    chave = ", ".join(f'"{c}"' for c in conflito)

    # CREATE TABLE AS ... WITH NO DATA em vez de LIKE: o LIKE copia a coluna
    # id como NOT NULL sem trazer o default da sequência, e o COPY, que não
    # inclui id, falha com NotNullViolation.
    conn.execute(
        text(
            f'CREATE TEMP TABLE "{temp}" ON COMMIT DROP AS '
            f'SELECT {lista} FROM "{tabela}" WITH NO DATA'
        )
    )
    copiar_para_tabela(conn, temp, df, colunas)
    conn.execute(
        text(f"""
        INSERT INTO "{tabela}" ({lista})
        SELECT {lista} FROM "{temp}"
        ON CONFLICT ({chave}) {acao}
        """)
    )
    return df.height


def _carregar_modalidades(conn: Connection, lic: pl.DataFrame) -> int:
    """Precisa vir antes de licitacao: codigo_modalidade é FK."""
    df = (
        lic.select(
            pl.col("codigo_modalidade").alias("codigo"),
            pl.col("modalidade").alias("nome"),
        )
        .filter(pl.col("codigo").is_not_null())
        .unique(subset=["codigo"])
    )
    return _via_temporaria(conn, df, "modalidade", ["codigo", "nome"], ["codigo"], ["nome"])


def _carregar_orgaos(conn: Connection, lic: pl.DataFrame) -> int:
    """Órgãos subordinados e superiores, numa passada.

    A hierarquia é auto-relacionada e a FK é diferida, então o superior pode
    ser inserido depois do subordinado - a verificação acontece no commit.
    Os superiores entram como órgãos próprios, com o nome que o CSV traz.
    """
    superiores = lic.select(
        pl.col("codigo_orgao_superior").alias("codigo_orgao"),
        pl.col("nome_orgao_superior").alias("nome"),
        pl.lit(None, dtype=pl.String).alias("codigo_orgao_superior"),
    )
    subordinados = lic.select(
        pl.col("codigo_orgao"),
        pl.col("nome_orgao").alias("nome"),
        pl.col("codigo_orgao_superior"),
    )
    # Subordinados por último: o unique com keep="last" preserva a hierarquia
    # quando um código aparece nos dois papéis.
    df = (
        pl.concat([superiores, subordinados])
        .filter(pl.col("codigo_orgao").is_not_null())
        .unique(subset=["codigo_orgao"], keep="last")
    )
    return _via_temporaria(
        conn,
        df,
        "orgao",
        ["codigo_orgao", "nome", "codigo_orgao_superior"],
        ["codigo_orgao"],
        ["nome"],
    )


def _carregar_ugs(conn: Connection, lic: pl.DataFrame) -> int:
    """Recebe uf e municipio, que dependem da UG e não da licitação."""
    df = (
        lic.select(
            pl.col("codigo_ug"),
            pl.col("nome_ug").alias("nome"),
            pl.col("uf"),
            pl.col("municipio"),
            pl.col("codigo_orgao"),
        )
        .filter(pl.col("codigo_ug").is_not_null())
        .unique(subset=["codigo_ug"])
    )
    return _via_temporaria(
        conn,
        df,
        "unidade_gestora",
        ["codigo_ug", "nome", "uf", "municipio", "codigo_orgao"],
        ["codigo_ug"],
        ["nome", "uf", "municipio"],
    )


def _carregar_fornecedores(conn: Connection, item: pl.DataFrame, part: pl.DataFrame) -> int:
    vazio = pl.DataFrame(schema={"cnpj": pl.String, "nome": pl.String})
    de_item = (
        item.select(pl.col("cnpj_vencedor").alias("cnpj"), pl.col("nome_vencedor").alias("nome"))
        if item.height
        else vazio
    )
    de_part = (
        part.select(
            pl.col("cnpj_participante").alias("cnpj"),
            pl.col("nome_participante").alias("nome"),
        )
        if part.height
        else vazio
    )
    df = (
        pl.concat([de_item, de_part])
        .filter(pl.col("cnpj").is_not_null() & (pl.col("cnpj").str.len_chars() > 0))
        .unique(subset=["cnpj"])
    )
    return _via_temporaria(conn, df, "fornecedor", ["cnpj", "nome"], ["cnpj"], ["nome"])


def _carregar_licitacoes(conn: Connection, lic: pl.DataFrame) -> int:
    df = lic.select(COLUNAS_LICITACAO).unique(subset=CHAVE_NATURAL, keep="last")
    return _via_temporaria(
        conn,
        df,
        "licitacao",
        COLUNAS_LICITACAO,
        CHAVE_NATURAL,
        ["situacao", "valor", "data_resultado"],
    )


def _carregar_filhos(conn: Connection, df: pl.DataFrame, tabela: str, colunas: list[str]) -> int:
    """Itens e participantes: resolve licitacao_id pela chave natural.

    O JOIN acontece em SQL, sem trazer as licitações para a memória do Python.

    Apaga e reinsere por licitação em vez de fazer upsert: item e participante
    não têm chave natural própria, e casar linha a linha seria mais caro e mais
    frágil que substituir o conjunto.

    As colunas de destino são explícitas porque o Parquet traz campos que
    pertencem a outras tabelas - nome_vencedor e nome_participante já foram
    para fornecedor.
    """
    if df.height == 0:
        return 0

    temp = f"tmp_{tabela}"
    lista = ", ".join(f'"{c}"' for c in colunas)
    selecao = ", ".join(f't."{c}"' for c in colunas)
    a_copiar = CHAVE_NATURAL + colunas

    conn.execute(
        text(f"""
        CREATE TEMP TABLE "{temp}" ON COMMIT DROP AS
        SELECT
            CAST(NULL AS text) AS numero_licitacao,
            CAST(NULL AS text) AS codigo_ug,
            CAST(NULL AS int) AS codigo_modalidade,
            {lista}
        FROM "{tabela}" WITH NO DATA
        """)
    )
    copiar_para_tabela(conn, temp, df.select(a_copiar), a_copiar)

    juncao = """
        JOIN licitacao l
          ON l.numero_licitacao = t.numero_licitacao
         AND l.codigo_ug = t.codigo_ug
         AND l.codigo_modalidade = t.codigo_modalidade
    """

    conn.execute(
        text(f"""
        DELETE FROM "{tabela}" WHERE licitacao_id IN (
            SELECT l.id FROM "{temp}" t {juncao}
        )
        """)
    )
    resultado = conn.execute(
        text(f"""
        INSERT INTO "{tabela}" (licitacao_id, {lista})
        SELECT l.id, {selecao} FROM "{temp}" t {juncao}
        """)
    )
    return resultado.rowcount
