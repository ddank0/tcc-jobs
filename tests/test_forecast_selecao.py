"""Seleção de séries elegíveis para treino.

O critério e o número de descartadas fazem parte do resultado: descartar em
silêncio é o que transforma recorte em viés. Medido na base real: 737 séries
com 60+ meses concentram 98,4% do volume.
"""

from decimal import Decimal

import polars as pl

from tcc_jobs.ml.forecast import Selecao, selecionar_series


def _series() -> pl.LazyFrame:
    """Três séries: uma longa, uma no limite exato, uma curta."""
    linhas: dict[str, list[object]] = {
        "competencia": [],
        "codigo_orgao": [],
        "codigo_modalidade": [],
        "quantidade_licitacoes": [],
        "valor_total": [],
    }

    def adiciona(orgao: str, meses: int) -> None:
        for i in range(meses):
            ano, mes = 2013 + i // 12, i % 12 + 1
            linhas["competencia"].append(f"{ano}{mes:02d}")
            linhas["codigo_orgao"].append(orgao)
            linhas["codigo_modalidade"].append(5)
            linhas["quantidade_licitacoes"].append(10 + i)
            linhas["valor_total"].append(Decimal("100.0000"))

    adiciona("26000", 60)  # elegível com folga
    adiciona("22000", 36)  # exatamente no limite: minimo_treino=24 + h=12
    adiciona("99999", 18)  # curta demais

    return pl.LazyFrame(linhas)


def test_seleciona_series_com_historia_suficiente() -> None:
    selecao = selecionar_series(_series(), minimo_treino=24, h=12)

    chaves = {(s.codigo_orgao, s.codigo_modalidade) for s in selecao.series}
    assert ("26000", 5) in chaves
    assert ("22000", 5) in chaves
    assert ("99999", 5) not in chaves


def test_descarte_e_contado_e_nao_silencioso() -> None:
    selecao = selecionar_series(_series(), minimo_treino=24, h=12)

    assert selecao.descartadas == 1
    assert selecao.elegiveis == 2


def test_serie_vem_ordenada_por_competencia() -> None:
    """O modelo pressupõe ordem temporal; embaralhado, o treino é inválido."""
    selecao = selecionar_series(_series(), minimo_treino=24, h=12)

    for serie in selecao.series:
        assert serie.competencias == sorted(serie.competencias)


def test_valores_acompanham_a_serie() -> None:
    selecao = selecionar_series(_series(), minimo_treino=24, h=12)
    longa = next(s for s in selecao.series if s.codigo_orgao == "26000")

    assert len(longa.quantidades) == 60
    assert longa.quantidades[0] == 10.0
    assert longa.quantidades[-1] == 69.0


def test_universo_vazio() -> None:
    vazio = pl.LazyFrame(
        {
            "competencia": [],
            "codigo_orgao": [],
            "codigo_modalidade": [],
            "quantidade_licitacoes": [],
            "valor_total": [],
        }
    )

    selecao = selecionar_series(vazio, minimo_treino=24, h=12)

    assert selecao.series == [] and selecao.descartadas == 0


def test_selecao_e_imutavel() -> None:
    import pytest

    selecao = selecionar_series(_series(), minimo_treino=24, h=12)

    assert isinstance(selecao, Selecao)
    with pytest.raises(AttributeError):
        selecao.series = []  # type: ignore[misc]
