from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from tcc_jobs.etl.agregacao import serie_mensal


def _entrada() -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            # Três valores assimétricos no grupo 202401/22000: mediana 200,
            # média 1100. Com dois pontos simétricos as duas coincidem, e o
            # teste da mediana não distinguiria uma da outra - justamente a
            # robustez a outlier que motiva o campo.
            "competencia": ["202401", "202401", "202401", "202401", "202402"],
            "codigo_orgao": ["22000", "22000", "22000", "26000", "22000"],
            "codigo_modalidade": [5, 5, 5, 8, 5],
            "valor": [
                Decimal("100.0000"),
                Decimal("200.0000"),
                Decimal("3000.0000"),
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

    assert linha["quantidade_licitacoes"][0] == 3
    assert linha["valor_total"][0] == Decimal("3300.0000")


def test_calcula_mediana() -> None:
    resultado = serie_mensal(_entrada()).collect()
    linha = resultado.filter(
        (pl.col("competencia") == "202401") & (pl.col("codigo_orgao") == "22000")
    )

    assert linha["valor_mediano"][0] == Decimal("200.0000")
    media = linha["valor_total"][0] / linha["quantidade_licitacoes"][0]
    assert linha["valor_mediano"][0] != media, "mediana precisa diferir da média aqui"


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


def _itens() -> pl.LazyFrame:
    """Itens de duas competências, com os sentinelas que a fonte usa.

    `-11` é "Sigiloso", `-2` é "Inválido" e `ESTRANG*` marca fornecedor
    estrangeiro sem CNPJ - ausência de dado, não fornecedor.
    """
    return pl.LazyFrame(
        {
            "competencia": ["202401", "202401", "202401", "202401", "202402", "202401"],
            "numero_licitacao": ["0001", "0001", "0002", "0003", "0004", "0005"],
            "codigo_ug": ["10", "10", "10", "20", "10", "10"],
            "codigo_modalidade": [5, 5, 5, 5, 5, 5],
            "cnpj_vencedor": [
                "11111111111111",
                "11111111111111",
                "11111111111111",
                "22222222222222",
                "11111111111111",
                "-11",
            ],
            "quantidade": [
                Decimal("2.0000"),
                Decimal("1.0000"),
                Decimal("1.0000"),
                Decimal("3.0000"),
                Decimal("1.0000"),
                Decimal("1.0000"),
            ],
            "valor_item": [
                Decimal("100.0000"),
                Decimal("300.0000"),
                Decimal("50.0000"),
                Decimal("10.0000"),
                Decimal("70.0000"),
                Decimal("999.0000"),
            ],
        },
        schema={
            "competencia": pl.String,
            "numero_licitacao": pl.String,
            "codigo_ug": pl.String,
            "codigo_modalidade": pl.Int32,
            "cnpj_vencedor": pl.String,
            "quantidade": pl.Decimal(18, 4),
            "valor_item": pl.Decimal(18, 4),
        },
    )


def test_serie_fornecedor_agrega_por_competencia_e_cnpj() -> None:
    from tcc_jobs.etl.agregacao import serie_fornecedor

    resultado = serie_fornecedor(_itens()).collect()
    linha = resultado.filter(
        (pl.col("competencia") == "202401") & (pl.col("cnpj") == "11111111111111")
    )

    # 3 itens em 202401: 2x100, 1x300, 1x50 = 200 + 300 + 50
    assert linha["itens_vencidos"][0] == 3
    assert linha["valor_total"][0] == Decimal("550.0000")


def test_conta_licitacoes_distintas_pela_chave_natural() -> None:
    """Dois itens da mesma licitação contam como uma licitação vencida.

    No silver não existe `licitacao_id` - ele é gerado pelo banco -, então a
    identidade é a chave natural.
    """
    from tcc_jobs.etl.agregacao import serie_fornecedor

    resultado = serie_fornecedor(_itens()).collect()
    linha = resultado.filter(
        (pl.col("competencia") == "202401") & (pl.col("cnpj") == "11111111111111")
    )

    # licitações 0001 (dois itens) e 0002 = duas distintas
    assert linha["licitacoes_distintas"][0] == 2


def test_serie_fornecedor_ignora_cnpj_sentinela() -> None:
    from tcc_jobs.etl.agregacao import serie_fornecedor

    resultado = serie_fornecedor(_itens()).collect()

    assert "-11" not in resultado["cnpj"].to_list()


def test_serie_fornecedor_separa_competencias() -> None:
    from tcc_jobs.etl.agregacao import serie_fornecedor

    resultado = serie_fornecedor(_itens()).collect()

    assert set(resultado["competencia"].to_list()) == {"202401", "202402"}


def test_valor_total_suporta_os_extremos_reais() -> None:
    """1.232 itens da base passam de 1e14. Com Decimal(18,4) a soma estoura."""
    from tcc_jobs.etl.agregacao import serie_fornecedor

    extremo = pl.LazyFrame(
        {
            "competencia": ["202401"],
            "numero_licitacao": ["0001"],
            "codigo_ug": ["10"],
            "codigo_modalidade": [5],
            "cnpj_vencedor": ["11111111111111"],
            # Cada fator cabe em Decimal(18,4); o produto é que não cabe.
            "quantidade": [Decimal("10000000.0000")],
            "valor_item": [Decimal("96019037032374.0000")],
        },
        schema={
            "competencia": pl.String,
            "numero_licitacao": pl.String,
            "codigo_ug": pl.String,
            "codigo_modalidade": pl.Int32,
            "cnpj_vencedor": pl.String,
            "quantidade": pl.Decimal(18, 4),
            "valor_item": pl.Decimal(18, 4),
        },
    )

    resultado = serie_fornecedor(extremo).collect()

    assert resultado["valor_total"][0] == Decimal("960190370323740000000.0000")


def test_ranking_total_deriva_da_serie_por_competencia() -> None:
    """A soma do ranking global tem que bater com a série por competência.

    Se divergirem, as duas tabelas contam coisas diferentes e a tela mostra
    números que não fecham entre si.
    """
    from tcc_jobs.etl.agregacao import ranking_fornecedor_total, serie_fornecedor

    serie = serie_fornecedor(_itens())
    total = ranking_fornecedor_total(serie).collect()
    serie_col = serie.collect()

    assert total["valor_total"].sum() == serie_col["valor_total"].sum()
    assert total["itens_vencidos"].sum() == serie_col["itens_vencidos"].sum()


def test_ranking_total_soma_as_competencias_do_mesmo_cnpj() -> None:
    from tcc_jobs.etl.agregacao import ranking_fornecedor_total, serie_fornecedor

    total = ranking_fornecedor_total(serie_fornecedor(_itens())).collect()
    linha = total.filter(pl.col("cnpj") == "11111111111111")

    assert linha.height == 1, "um CNPJ aparece uma vez só no ranking global"
    # 202401: 3 itens, 550 | 202402: 1 item, 70
    assert linha["itens_vencidos"][0] == 4
    assert linha["valor_total"][0] == Decimal("620.0000")
    assert linha["licitacoes_distintas"][0] == 3


def test_ambas_devolvem_lazyframe() -> None:
    """O núcleo não materializa: o collect é uma vez só, na casca."""
    from tcc_jobs.etl.agregacao import ranking_fornecedor_total, serie_fornecedor

    serie = serie_fornecedor(_itens())
    assert isinstance(serie, pl.LazyFrame)
    assert isinstance(ranking_fornecedor_total(serie), pl.LazyFrame)


def test_colunas_batem_com_as_tabelas() -> None:
    from tcc_jobs.etl.agregacao import (
        COLUNAS_RANKING_TOTAL,
        COLUNAS_SERIE_FORNECEDOR,
        ranking_fornecedor_total,
        serie_fornecedor,
    )

    serie = serie_fornecedor(_itens())
    assert set(serie.collect().columns) == set(COLUNAS_SERIE_FORNECEDOR)
    assert set(ranking_fornecedor_total(serie).collect().columns) == set(COLUNAS_RANKING_TOTAL)


@pytest.mark.lento
def test_chave_natural_nao_se_repete_entre_competencias() -> None:
    """A competência da agregação vem do nome do arquivo em silver.

    Isso só é correto porque nenhuma licitação aparece em duas competências.
    Se aparecesse, os itens dela seriam contados duas vezes e atribuídos à
    competência errada. Hoje não acontece - 1.743.023 linhas para 1.743.023
    chaves distintas -, e este teste é o que impede a premissa de envelhecer
    em silêncio.

    Roda contra o silver real, fora da suíte rápida.
    """
    caminho = Path("/data/silver/licitacao")
    if not caminho.exists():
        pytest.skip("silver não disponível neste ambiente")

    lf = pl.scan_parquet(f"{caminho}/*.parquet")
    total = lf.select(pl.len()).collect().item()
    distintas = (
        lf.select(["numero_licitacao", "codigo_ug", "codigo_modalidade"])
        .unique()
        .select(pl.len())
        .collect()
        .item()
    )

    assert total == distintas, (
        f"{total - distintas} chaves naturais repetidas: a competência não pode "
        "mais ser derivada do nome do arquivo"
    )
