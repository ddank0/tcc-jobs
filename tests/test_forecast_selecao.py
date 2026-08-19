"""Seleção de séries elegíveis para treino.

O critério e o número de descartadas fazem parte do resultado: descartar em
silêncio é o que transforma recorte em viés. Medido na base real: 737 séries
com 60+ meses concentram 98,4% do volume.
"""

from decimal import Decimal

import polars as pl

from tcc_jobs.ml.forecast import Selecao, selecionar_series


def _series() -> pl.LazyFrame:
    """Três séries num universo que termina em 201712.

    A elegibilidade é pelo calendário: quem parou cedo ganha zeros e continua
    elegível; o descarte real é quem começa tarde demais.
    """
    linhas: dict[str, list[object]] = {
        "competencia": [],
        "codigo_orgao": [],
        "codigo_modalidade": [],
        "quantidade_licitacoes": [],
        "valor_total": [],
    }

    def adiciona(orgao: str, meses: int, inicio: int = 0) -> None:
        # A elegibilidade é pelo calendário: série que parou cedo ganha zeros
        # até o fim e continua elegível. O descarte real é a série que COMEÇA
        # tarde demais para ter história.
        for i in range(inicio, inicio + meses):
            ano, mes = 2013 + i // 12, i % 12 + 1
            linhas["competencia"].append(f"{ano}{mes:02d}")
            linhas["codigo_orgao"].append(orgao)
            linhas["codigo_modalidade"].append(5)
            linhas["quantidade_licitacoes"].append(10 + (i - inicio))
            linhas["valor_total"].append(Decimal("100.0000"))

    adiciona("26000", 60)  # elegível com folga; define o fim do universo
    adiciona("22000", 24, inicio=24)  # calendário de 36 meses: no limite exato
    adiciona("99999", 6, inicio=54)  # começa tarde: 6 meses de calendário

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

    # a série que começa no mês 24 ganha zeros do 48 ao 59: parou de licitar
    no_limite = next(s for s in selecao.series if s.codigo_orgao == "22000")
    assert len(no_limite.quantidades) == 36
    assert no_limite.quantidades[-12:] == [0.0] * 12


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


def test_mes_sem_linha_vira_zero_e_nao_buraco() -> None:
    """Ausência de linha em serie_mensal significa zero licitações no mês,
    não dado faltante. Medido: 84,9% das séries reais têm buraco, somando
    51.950 meses. Sem preencher, a posição na lista deixa de corresponder ao
    mês do calendário e a sazonalidade m=12 desalinha em quase toda série."""
    linhas: dict[str, list[object]] = {
        "competencia": ["201301", "201303", "201304"],  # 201302 ausente
        "codigo_orgao": ["26000"] * 3,
        "codigo_modalidade": [5] * 3,
        "quantidade_licitacoes": [10, 30, 40],
        "valor_total": [Decimal("100.0000")] * 3,
    }
    # completa até 36 meses para ser elegível
    for i in range(4, 37):
        ano, mes = 2013 + (i - 1) // 12, (i - 1) % 12 + 1
        linhas["competencia"].append(f"{ano}{mes:02d}")
        linhas["codigo_orgao"].append("26000")
        linhas["codigo_modalidade"].append(5)
        linhas["quantidade_licitacoes"].append(50)
        linhas["valor_total"].append(Decimal("100.0000"))

    selecao = selecionar_series(pl.LazyFrame(linhas), minimo_treino=24, h=12)
    serie = selecao.series[0]

    assert len(serie.competencias) == 36
    assert serie.competencias[1] == "201302"
    assert serie.quantidades[1] == 0.0
    assert serie.valores[1] == 0.0
    assert serie.quantidades[2] == 30.0


def test_series_alinham_no_fim_do_calendario() -> None:
    """Uma série que 'para' antes do fim ganha zeros até a última competência
    do universo: órgão que deixou de licitar tem zero licitações, e sem o
    alinhamento a previsão dela partiria de um presente que não existe."""
    linhas: dict[str, list[object]] = {
        "competencia": [],
        "codigo_orgao": [],
        "codigo_modalidade": [],
        "quantidade_licitacoes": [],
        "valor_total": [],
    }
    for i in range(40):
        ano, mes = 2013 + i // 12, i % 12 + 1
        linhas["competencia"].append(f"{ano}{mes:02d}")
        linhas["codigo_orgao"].append("26000")
        linhas["codigo_modalidade"].append(5)
        linhas["quantidade_licitacoes"].append(10)
        linhas["valor_total"].append(Decimal("100.0000"))
    # segunda série para 4 meses antes do fim
    for i in range(36):
        ano, mes = 2013 + i // 12, i % 12 + 1
        linhas["competencia"].append(f"{ano}{mes:02d}")
        linhas["codigo_orgao"].append("22000")
        linhas["codigo_modalidade"].append(5)
        linhas["quantidade_licitacoes"].append(20)
        linhas["valor_total"].append(Decimal("100.0000"))

    selecao = selecionar_series(pl.LazyFrame(linhas), minimo_treino=24, h=12)
    curta = next(s for s in selecao.series if s.codigo_orgao == "22000")

    assert len(curta.competencias) == 40
    assert curta.quantidades[-4:] == [0.0, 0.0, 0.0, 0.0]
