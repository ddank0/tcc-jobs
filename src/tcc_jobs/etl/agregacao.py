"""Agregações que alimentam a previsão e a análise histórica.

Núcleo funcional: recebe LazyFrame e devolve LazyFrame, sem collect. É isso
que permite ao motor enxergar o encadeamento inteiro e otimizar - projetando
apenas as colunas usadas e empurrando filtros para a leitura.

A casca que lê do banco e grava o resultado fica em db/agregacao_carga.py:
misturar as duas aqui violaria o contrato de pureza do núcleo.
"""

import polars as pl

COLUNAS_SERIE = [
    "competencia",
    "codigo_orgao",
    "codigo_modalidade",
    "quantidade_licitacoes",
    "valor_total",
    "valor_mediano",
]


def serie_mensal(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Agrega licitações por competência, órgão e modalidade.

    É a entrada do módulo de previsão: cada combinação vira uma série
    temporal, e a contagem e o valor total são os dois alvos previstos.
    """
    return lf.group_by(["competencia", "codigo_orgao", "codigo_modalidade"]).agg(
        pl.len().alias("quantidade_licitacoes"),
        pl.col("valor").sum().alias("valor_total"),
        pl.col("valor").median().cast(pl.Decimal(18, 4)).alias("valor_mediano"),
    )
