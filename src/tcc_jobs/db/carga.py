"""Carga de silver para o PostgreSQL.

Casca imperativa. A idempotência é o requisito central: reprocessar a mesma
competência não pode duplicar registros.

COPY não suporta ON CONFLICT, e é o COPY que dá a velocidade - 17x mais rápido
que ORM. A conciliação é carregar numa tabela temporária e depois fazer
INSERT ... ON CONFLICT a partir dela.
"""

import logging
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

import polars as pl
from sqlalchemy import Connection, Engine, text

from tcc_jobs.core.competencia import Competencia
from tcc_jobs.db.copiador import copiar_para_tabela
from tcc_jobs.db.log_ingestao import registrar
from tcc_jobs.etl.armazenamento import Armazenamento

logger = logging.getLogger(__name__)

CHAVE_NATURAL = ["numero_licitacao", "codigo_ug", "codigo_modalidade"]

# As duas tabelas cujas FKs saem durante a carga inicial. São as que têm
# volume: 74,8M e 14,2M linhas.
TABELAS_FILHAS = ("item_licitacao", "participante_licitacao")

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
    lidas: dict[str, int] = field(default_factory=dict)
    erro: str | None = None


def carregar(
    competencias: list[Competencia],
    armazenamento: Armazenamento,
    engine: Engine,
    carga_inicial: bool = False,
) -> list[ResultadoCarga]:
    """Carrega silver no PostgreSQL, uma competência por transação.

    carga_inicial remove as chaves estrangeiras das tabelas filhas durante o
    lote inteiro e as recria no fim. Exige lock exclusivo e só deve ser usado
    com o banco fora de uso - ver `_sem_chaves_estrangeiras`.
    """
    if not carga_inicial:
        return [_carregar_uma(c, armazenamento, engine) for c in competencias]

    with _sem_chaves_estrangeiras(engine, TABELAS_FILHAS):
        return [_carregar_uma(c, armazenamento, engine) for c in competencias]


def _ler_silver(armazenamento: Armazenamento, c: Competencia, tabela: str) -> pl.DataFrame:
    caminho = armazenamento.caminho_silver(c, tabela)
    return pl.read_parquet(caminho) if caminho.exists() else pl.DataFrame()


def _carregar_uma(
    competencia: Competencia,
    armazenamento: Armazenamento,
    engine: Engine,
) -> ResultadoCarga:
    resultado = ResultadoCarga(competencia=competencia)
    iniciado = datetime.now(UTC).replace(tzinfo=None)

    try:
        lic = _ler_silver(armazenamento, competencia, "licitacao")
        item = _ler_silver(armazenamento, competencia, "item")
        part = _ler_silver(armazenamento, competencia, "participante")

        resultado.lidas = {
            "licitacao": lic.height,
            "item": item.height,
            "participante": part.height,
        }

        if lic.height == 0:
            # Sem `return`: ele sairia da função antes de _registrar, e o
            # caminho de falha é justamente o que o RF10 precisa registrar.
            raise ValueError("silver ausente ou vazio - rode ingest primeiro")

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

    except ValueError as erro:  # silver ausente: esperado, não merece stack trace
        resultado.erro = str(erro)
        logger.warning("load %s: %s", competencia, erro)
    except Exception as erro:  # noqa: BLE001 - uma competência ruim não derruba o lote
        resultado.erro = f"{type(erro).__name__}: {erro}"
        logger.exception("load %s falhou", competencia)

    try:
        _registrar(engine, competencia, resultado, iniciado)
    except Exception:
        # O registro é para observabilidade; falhar nele não pode derrubar o
        # lote, que é o contrato declarado desta função.
        logger.exception("load %s: falha ao gravar ingestao_log", competencia)

    return resultado


def _registrar(
    engine: Engine,
    competencia: Competencia,
    resultado: ResultadoCarga,
    iniciado: datetime,
) -> None:
    """Grava o resultado em ingestao_log. Atende ao RF10.

    Fica dentro de _carregar_uma para que o registro não dependa de quem chama
    lembrar de fazê-lo.
    """
    registrar(
        engine,
        competencia=competencia,
        arquivo=f"{competencia}_silver",
        lidas=sum(resultado.lidas.values()),
        inseridas=sum(resultado.inseridas.get(t, 0) for t in ("licitacao", "item", "participante")),
        # A carga não atualiza fato: licitacao usa ON CONFLICT DO NOTHING e os
        # filhos são apagados e reinseridos. O zero aqui é medida, não omissão.
        atualizadas=0,
        rejeitadas=max(
            0,
            sum(resultado.lidas.values())
            - sum(resultado.inseridas.get(t, 0) for t in ("licitacao", "item", "participante")),
        ),
        iniciado_em=iniciado,
        finalizado_em=datetime.now(UTC).replace(tzinfo=None),
        status="erro" if resultado.erro else "sucesso",
        mensagem_erro=resultado.erro,
    )


@contextmanager
def _sem_chaves_estrangeiras(engine: Engine, tabelas: Sequence[str]) -> Generator[None]:
    """Remove as FKs das tabelas durante o lote e as recria uma única vez.

    O PostgreSQL verifica FK por trigger, uma vez por linha inserida. Medido em
    participante_licitacao com 161 mil linhas: os dois triggers consomem 7,2s
    dos 8,4s da carga. Recriar a constraint valida em lote e é mais rápido.

    Diferir a verificação para o commit não resolve: o custo apenas migra, e o
    tempo total fica igual. Foi medido.

    **O escopo é o lote, não a competência - e isso não é detalhe.** O
    ADD CONSTRAINT revalida a tabela filha *inteira*, não as linhas novas.
    Medido na base cheia: 15,9s para uma única FK de participante_licitacao com
    74,8 milhões de linhas. Fazer isso por competência tornaria a carga
    O(N x M), e foi o que aconteceu na primeira carga completa: a competência
    202404, com 721 licitações, levou 31s, enquanto 201301, com 7.104, levou
    2,1s. Dez vezes menos dado, quinze vezes mais tempo.

    ATENÇÃO - só para carga inicial, com o banco fora de uso. O DROP CONSTRAINT
    exige ACCESS EXCLUSIVE, que conflita com qualquer leitura concorrente: se a
    API estiver consultando, a carga trava esperando o lock. É por isso que
    depende de flag explícita em vez de ser o padrão.

    O DROP é commitado antes do lote começar, então morte abrupta do processo
    (SIGKILL, queda de energia) deixa o banco sem as FKs. Recuperar exige
    recriá-las à mão - o preço de a janela sem constraint atravessar várias
    transações. Aceitável porque o modo pressupõe banco fora de uso.
    """
    # CAST(... AS regclass) em vez de ::regclass: o :: colide com a sintaxe de
    # parâmetro do SQLAlchemy e vira erro de sintaxe.
    definicoes: list[tuple[str, str, str]] = []
    with engine.begin() as conn:
        for tabela in tabelas:
            for nome, definicao in conn.execute(
                text("""
                SELECT conname, pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE conrelid = CAST(:tabela AS regclass) AND contype = 'f'
                """),
                {"tabela": tabela},
            ).all():
                definicoes.append((tabela, nome, definicao))
                conn.execute(text(f'ALTER TABLE "{tabela}" DROP CONSTRAINT "{nome}"'))

    try:
        yield
    finally:
        # Conexão nova de propósito: se o lote falhou, a transação que abortou
        # não aceita mais comando algum, e o ADD CONSTRAINT morreria com
        # "current transaction is aborted" - deixando o banco sem FK.
        with engine.begin() as conn:
            for tabela, nome, definicao in definicoes:
                conn.execute(text(f'ALTER TABLE "{tabela}" ADD CONSTRAINT "{nome}" {definicao}'))


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


def _carregar_filhos(
    conn: Connection,
    df: pl.DataFrame,
    tabela: str,
    colunas: list[str],
) -> int:
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

    insercao = text(f"""
        INSERT INTO "{tabela}" (licitacao_id, {lista})
        SELECT l.id, {selecao} FROM "{temp}" t {juncao}
    """)

    return conn.execute(insercao).rowcount
