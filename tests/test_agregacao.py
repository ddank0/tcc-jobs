from decimal import Decimal

import polars as pl

from tcc_jobs.etl.agregacao import serie_mensal


def _entrada() -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "competencia": ["202401", "202401", "202401", "202402"],
            "codigo_orgao": ["22000", "22000", "26000", "22000"],
            "codigo_modalidade": [5, 5, 8, 5],
            "valor": [
                Decimal("100.0000"),
                Decimal("300.0000"),
                Decimal("50.0000"),
                Decimal("200.0000"),
            ],
        },
        schema={
            "competencia": pl.String,
            "codigo_orgao": pl.String,
            "codigo_modalidade": pl.Int32,
            "valor": pl.Decimal(18, 4),
        },
    )


def test_agrupa_por_competencia_orgao_e_modalidade() -> None:
    resultado = serie_mensal(_entrada()).collect()

    assert resultado.height == 3


def test_conta_e_soma() -> None:
    resultado = serie_mensal(_entrada()).collect()
    linha = resultado.filter(
        (pl.col("competencia") == "202401") & (pl.col("codigo_orgao") == "22000")
    )

    assert linha["quantidade_licitacoes"][0] == 2
    assert linha["valor_total"][0] == Decimal("400.0000")


def test_calcula_mediana() -> None:
    resultado = serie_mensal(_entrada()).collect()
    linha = resultado.filter(
        (pl.col("competencia") == "202401") & (pl.col("codigo_orgao") == "22000")
    )

    assert linha["valor_mediano"][0] == Decimal("200.0000")


def test_devolve_lazyframe_sem_materializar() -> None:
    """O ganho do Polars vem da avaliação lazy: o núcleo não chama collect,
    para o motor enxergar o encadeamento inteiro e otimizar."""
    assert isinstance(serie_mensal(_entrada()), pl.LazyFrame)


def test_ignora_valor_nulo_na_soma() -> None:
    entrada = pl.LazyFrame(
        {
            "competencia": ["202401", "202401"],
            "codigo_orgao": ["22000", "22000"],
            "codigo_modalidade": [5, 5],
            "valor": [Decimal("100.0000"), None],
        },
        schema={
            "competencia": pl.String,
            "codigo_orgao": pl.String,
            "codigo_modalidade": pl.Int32,
            "valor": pl.Decimal(18, 4),
        },
    )

    resultado = serie_mensal(entrada).collect()

    assert resultado["quantidade_licitacoes"][0] == 2
    assert resultado["valor_total"][0] == Decimal("100.0000")


def test_colunas_batem_com_a_tabela() -> None:
    """O resultado vai direto para serie_mensal via COPY: coluna a mais ou a
    menos quebraria a carga."""
    from tcc_jobs.etl.agregacao import COLUNAS_SERIE

    resultado = serie_mensal(_entrada()).collect()

    assert set(resultado.columns) == set(COLUNAS_SERIE)
