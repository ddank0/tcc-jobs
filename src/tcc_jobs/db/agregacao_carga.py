"""Casca da agregação: lê do banco, chama o núcleo puro, grava o resultado.

Fica em db/ e não em etl/ porque importa o copiador. Se estivesse junto do
núcleo, o import-linter acusaria a violação - com razão.
"""

import logging

import polars as pl
from sqlalchemy import Engine, text

from tcc_jobs.db.copiador import copiar_para_tabela
from tcc_jobs.etl.agregacao import (
    COLUNAS_RANKING_TOTAL,
    COLUNAS_SERIE,
    COLUNAS_SERIE_FORNECEDOR,
    ranking_fornecedor_total,
    serie_fornecedor,
    serie_mensal,
)
from tcc_jobs.etl.armazenamento import Armazenamento

logger = logging.getLogger(__name__)

# Lê do banco, não de silver: o banco já tem as duplicatas resolvidas pela
# chave natural, e silver não. O órgão vem por JOIN porque a licitação
# referencia a unidade gestora, e é a UG que pertence ao órgão.
CONSULTA = """
    SELECT l.competencia, u.codigo_orgao, l.codigo_modalidade, l.valor
    FROM licitacao l
    JOIN unidade_gestora u ON u.codigo_ug = l.codigo_ug
"""


def agregar(engine: Engine) -> int:
    """Recalcula serie_mensal a partir de licitacao.

    Continua lendo do banco: são 1,74 milhão de linhas, e `read_database` dá
    conta. Para os fornecedores, que precisam de 14,2 milhões, a fonte é o
    silver - ver `agregar_fornecedores`.
    """
    with engine.begin() as conn:
        df = pl.read_database(CONSULTA, connection=conn)

        if df.height == 0:
            logger.warning("aggregate: nenhuma licitação carregada")
            return 0

        agregado = serie_mensal(df.lazy()).collect()

        conn.execute(text("TRUNCATE serie_mensal RESTART IDENTITY"))
        total = copiar_para_tabela(conn, "serie_mensal", agregado, COLUNAS_SERIE)

    logger.info("aggregate: %d linhas em serie_mensal", total)
    return total


def agregar_fornecedores(engine: Engine, armazenamento: Armazenamento) -> tuple[int, int]:
    """Recalcula as duas tabelas de ranking de fornecedores.

    Lê do silver, não do banco. Medido: `read_database` sobre os 14,2 milhões
    de linhas de `item_licitacao` leva 205s, dos quais 187s são só a
    transferência pelo socket. O `scan_parquet` equivalente leva 2,3s, porque o
    Parquet é colunar e o scan lazy projeta apenas as quatro colunas usadas.

    O custo é depender dos parquets em disco: limpar o silver quebra este job.

    A competência vem do nome do arquivo, e não de um join com licitação. Isso
    só é válido porque nenhuma chave natural aparece em duas competências -
    premissa travada por `test_chave_natural_nao_se_repete_entre_competencias`.
    """
    padrao = f"{armazenamento.silver}/item/*.parquet"

    if not list((armazenamento.silver / "item").glob("*.parquet")):
        logger.warning("aggregate: nenhum parquet de item em silver")
        return 0, 0

    itens = pl.scan_parquet(padrao, include_file_paths="arquivo").with_columns(
        pl.col("arquivo").str.extract(r"(\d{6})\.parquet$").alias("competencia")
    )

    serie = serie_fornecedor(itens)
    # Um collect por tabela: o global deriva da série, então o encadeamento
    # inteiro chega ao motor de uma vez em cada caso.
    por_competencia = serie.collect()
    global_ = ranking_fornecedor_total(por_competencia.lazy()).collect()

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE ranking_fornecedor RESTART IDENTITY"))
        conn.execute(text("TRUNCATE ranking_fornecedor_total"))
        total_serie = copiar_para_tabela(
            conn, "ranking_fornecedor", por_competencia, COLUNAS_SERIE_FORNECEDOR
        )
        total_global = copiar_para_tabela(
            conn, "ranking_fornecedor_total", global_, COLUNAS_RANKING_TOTAL
        )

    logger.info(
        "aggregate: %d linhas em ranking_fornecedor, %d em ranking_fornecedor_total",
        total_serie,
        total_global,
    )
    return total_serie, total_global
