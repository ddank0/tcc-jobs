"""Matriz de atributos: uma linha por licitação, contextualizada por modalidade.

Medido no dado real: 70,3% das licitações têm participante único - a natureza
de Dispensa e Inexigibilidade (98%), mas exceção em Pregão (6-11%). Feature
absoluta apontaria o rito, não o desvio; daí tudo relativo à modalidade.
"""

from decimal import Decimal

import polars as pl

from tcc_jobs.ml.features import COLUNAS_FEATURES, montar_features

CHAVE = ["numero_licitacao", "codigo_ug", "codigo_modalidade"]


def _licitacoes() -> pl.LazyFrame:
    # modalidade 5 (competitiva): três licitações; modalidade 6: duas
    return pl.LazyFrame(
        {
            "numero_licitacao": ["0001", "0002", "0003", "0004", "0005", "0006"],
            "codigo_ug": ["10", "10", "20", "10", "20", "20"],
            "codigo_modalidade": [5, 5, 5, 6, 6, 5],
            "codigo_orgao": ["26000", "26000", "22000", "26000", "22000", "22000"],
            "competencia": ["202401", "202401", "202402", "202401", "202402", "202402"],
            "valor": [
                Decimal("100.0000"),
                Decimal("100000.0000"),  # 1000x a mediana do grupo
                Decimal("100.0000"),
                Decimal("500.0000"),
                Decimal("500.0000"),
                None,  # valor nulo: 3,6% do real
            ],
        }
    )


def _participantes() -> pl.LazyFrame:
    linhas = {
        "numero_licitacao": [],
        "codigo_ug": [],
        "codigo_modalidade": [],
        "cnpj_participante": [],
        "flag_vencedor": [],
    }

    def add(num: str, ug: str, mod: int, cnpjs_e_flags: list[tuple[str, bool]]) -> None:
        for cnpj, flag in cnpjs_e_flags:
            linhas["numero_licitacao"].append(num)
            linhas["codigo_ug"].append(ug)
            linhas["codigo_modalidade"].append(mod)
            linhas["cnpj_participante"].append(cnpj)
            linhas["flag_vencedor"].append(flag)

    add("0001", "10", 5, [("A", True), ("B", False), ("C", False)])
    add("0002", "10", 5, [("A", True)])  # único numa modalidade competitiva
    add("0003", "20", 5, [("A", True), ("B", False)])
    add("0004", "10", 6, [("D", True)])  # único numa modalidade onde é a norma
    add("0005", "20", 6, [("D", True)])
    add("0006", "20", 5, [("E", False), ("F", False)])  # ninguém venceu: 0,7% do real
    return pl.LazyFrame(linhas)


def _itens() -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "numero_licitacao": ["0001", "0001", "0002", "0004"],
            "codigo_ug": ["10", "10", "10", "10"],
            "codigo_modalidade": [5, 5, 5, 6],
            "codigo_item_compra": ["X1", "X2", "X1", "X3"],
            "quantidade": [Decimal("1.0000")] * 3 + [Decimal("2000000000.0000")],
            "valor_item": [
                Decimal("50.0000"),
                Decimal("30.0000"),
                Decimal("5000.0000"),  # 100x a mediana do item X1
                Decimal("4800000.0000"),  # implausível
            ],
        }
    )


def _montada() -> pl.DataFrame:
    return montar_features(_licitacoes(), _itens(), _participantes()).collect()


def test_uma_linha_por_licitacao_com_as_colunas_do_contrato() -> None:
    m = _montada()

    assert m.height == 6
    assert set(m.columns) == set(CHAVE) | set(COLUNAS_FEATURES)


def test_razao_de_valor_contextualizada_pelo_grupo() -> None:
    m = _montada()
    cara = m.filter(pl.col("numero_licitacao") == "0002")

    # grupo (26000, 5): valores 100 e 100000 -> mediana 50050; razão ~2
    assert cara["razao_valor_grupo"][0] > 1.0


def test_participantes_relativo_a_modalidade() -> None:
    """O único do Pregão destoa; o único da Dispensa não."""
    m = _montada()
    unico_competitivo = m.filter(pl.col("numero_licitacao") == "0002")
    unico_por_rito = m.filter(pl.col("numero_licitacao") == "0004")

    # modalidade 5 tem medianas de participantes >1; modalidade 6, mediana 1
    assert unico_competitivo["razao_participantes_modalidade"][0] < 1.0
    assert unico_por_rito["razao_participantes_modalidade"][0] == 1.0


def test_taxa_de_vitoria_do_vencedor_no_orgao() -> None:
    m = _montada()
    l1 = m.filter(pl.col("numero_licitacao") == "0001")

    # A venceu 0001 e 0002 no órgão 26000: 2 vitórias / 2 disputas dele lá
    assert l1["taxa_vitoria_vencedor"][0] == 1.0


def test_hhi_do_orgao_em_0_1() -> None:
    m = _montada()

    assert m["hhi_orgao"].is_between(0.0, 1.0).all()


def test_sem_vencedor_vira_flag() -> None:
    m = _montada()

    assert m.filter(pl.col("numero_licitacao") == "0006")["sem_vencedor"][0] is True
    assert m.filter(pl.col("numero_licitacao") == "0001")["sem_vencedor"][0] is False


def test_item_implausivel_vira_flag_e_sai_da_razao() -> None:
    m = _montada()
    com_implausivel = m.filter(pl.col("numero_licitacao") == "0004")

    assert com_implausivel["contem_item_implausivel"][0] is True
    # a razão de item do 0004 não pode vir do item implausível
    assert (
        com_implausivel["razao_item_max"][0] is None or com_implausivel["razao_item_max"][0] < 100.0
    )


def test_licitacao_sem_participante_nao_some() -> None:
    """2% do real: entra com os atributos de participação nulos ou neutros."""
    so_lic = pl.LazyFrame(
        {
            "numero_licitacao": ["9999"],
            "codigo_ug": ["10"],
            "codigo_modalidade": [5],
            "codigo_orgao": ["26000"],
            "competencia": ["202401"],
            "valor": [Decimal("100.0000")],
        }
    )
    vazio_p = _participantes().filter(pl.col("numero_licitacao") == "nunca")
    vazio_i = _itens().filter(pl.col("numero_licitacao") == "nunca")

    m = montar_features(so_lic, vazio_i, vazio_p).collect()

    assert m.height == 1


def test_valor_nulo_nao_explode_a_razao() -> None:
    m = _montada()
    nulo = m.filter(pl.col("numero_licitacao") == "0006")

    assert nulo["razao_valor_grupo"][0] is None


def test_sem_nulos_inesperados_nas_flags() -> None:
    m = _montada()

    assert m["sem_vencedor"].null_count() == 0
    assert m["contem_item_implausivel"].null_count() == 0


def test_devolve_lazyframe() -> None:
    assert isinstance(montar_features(_licitacoes(), _itens(), _participantes()), pl.LazyFrame)
