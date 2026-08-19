"""Porta de plausibilidade: separa erro de preenchimento de contratação atípica.

Medido no dado real: 2,06% dos itens têm quantidade x valor_item acima de
R$ 1 bilhão, com extremo de R$ 9,6 quatrilhões num único item - dois bilhões
de unidades de um convênio médico. São erro de digitação da fonte, e um
detector treinado com eles no espaço de features aponta digitação, não padrão
atípico de contratação. A distinção precisa vir ANTES do detector, porque
muda o que entra como atributo.
"""

from decimal import Decimal

import polars as pl

from tcc_jobs.ml.features import CORTE_PLAUSIBILIDADE, marcar_plausibilidade


def _itens() -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "numero_licitacao": ["0001", "0001", "0002", "0003"],
            "codigo_ug": ["10"] * 4,
            "codigo_modalidade": [5] * 4,
            "quantidade": [
                Decimal("2.0000"),
                Decimal("2000000000.0000"),  # 2 bi de unidades
                Decimal("10.0000"),
                Decimal("1.0000"),
            ],
            "valor_item": [
                Decimal("100.0000"),
                Decimal("4800000.0000"),  # x 2 bi = 9,6 quatrilhões
                Decimal("50000.0000"),
                Decimal("999999999.0000"),  # 999,99 mi: abaixo do corte
            ],
        }
    )


def test_marca_item_com_produto_acima_do_corte() -> None:
    marcado = marcar_plausibilidade(_itens()).collect()

    assert marcado["plausivel"].to_list() == [True, False, True, True]


def test_o_corte_e_por_item_e_nao_por_licitacao() -> None:
    """A licitação 0001 tem um item normal e um implausível: o normal fica."""
    marcado = marcar_plausibilidade(_itens()).collect()
    da_0001 = marcado.filter(pl.col("numero_licitacao") == "0001")

    assert da_0001["plausivel"].to_list() == [True, False]


def test_exatamente_no_corte_e_plausivel() -> None:
    """O corte é exclusivo: 1 bilhão exato passa, acima não."""
    borda = pl.LazyFrame(
        {
            "numero_licitacao": ["0001", "0002"],
            "codigo_ug": ["10", "10"],
            "codigo_modalidade": [5, 5],
            "quantidade": [Decimal("1.0000"), Decimal("1.0000")],
            "valor_item": [
                Decimal(CORTE_PLAUSIBILIDADE),
                Decimal(CORTE_PLAUSIBILIDADE) + Decimal("0.0001"),
            ],
        }
    )

    marcado = marcar_plausibilidade(borda).collect()

    assert marcado["plausivel"].to_list() == [True, False]


def test_nulo_e_plausivel() -> None:
    """Valor ou quantidade nula não é implausível - é ausência de dado, e o
    tratamento de nulo pertence às features, não à porta."""
    nulos = pl.LazyFrame(
        {
            "numero_licitacao": ["0001"],
            "codigo_ug": ["10"],
            "codigo_modalidade": [5],
            "quantidade": [None],
            "valor_item": [Decimal("100.0000")],
        },
        schema_overrides={"quantidade": pl.Decimal(18, 4)},
    )

    marcado = marcar_plausibilidade(nulos).collect()

    assert marcado["plausivel"].to_list() == [True]


def test_preserva_as_colunas_originais() -> None:
    entrada = _itens().collect()
    saida = marcar_plausibilidade(_itens()).collect()

    assert set(entrada.columns) | {"plausivel"} == set(saida.columns)
    assert saida.height == entrada.height


def test_devolve_lazyframe() -> None:
    assert isinstance(marcar_plausibilidade(_itens()), pl.LazyFrame)
