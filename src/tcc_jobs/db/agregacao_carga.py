"""Casca da agregação: lê do banco, chama o núcleo puro, grava o resultado.

Fica em db/ e não em etl/ porque importa o copiador. Se estivesse junto do
núcleo, o import-linter acusaria a violação - com razão.
"""

import logging

import polars as pl
from sqlalchemy import Engine, text

from tcc_jobs.db.copiador import copiar_para_tabela
from tcc_jobs.etl.agregacao import COLUNAS_SERIE, serie_mensal

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
    """Recalcula serie_mensal a partir de licitacao."""
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
