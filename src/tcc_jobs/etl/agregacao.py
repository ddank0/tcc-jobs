"""Agregações que alimentam a previsão e a análise histórica.

Núcleo funcional: recebe LazyFrame e devolve LazyFrame, sem collect. É isso
que permite ao motor enxergar o encadeamento inteiro e otimizar - projetando
apenas as colunas usadas e empurrando filtros para a leitura.

A casca que lê do banco e grava o resultado fica em db/agregacao_carga.py:
misturar as duas aqui violaria o contrato de pureza do núcleo.
"""

import polars as pl

# A identidade da licitação no silver é a chave natural: `licitacao_id` só
# existe depois da carga, porque é o banco que o gera.
CHAVE_NATURAL = ["numero_licitacao", "codigo_ug", "codigo_modalidade"]

# CNPJs que a fonte usa como marcador de ausência, não como fornecedor.
# `-11` é "Sigiloso", `-2` é "Inválido", e `ESTRANG*` marca fornecedor
# estrangeiro sem CNPJ. Deixá-los entrar criaria vencedor fictício no ranking.
CNPJ_SENTINELA = ["-11", "-2"]
PREFIXO_SENTINELA = "ESTRANG"

COLUNAS_SERIE_FORNECEDOR = [
    "competencia",
    "cnpj",
    "itens_vencidos",
    "licitacoes_distintas",
    "valor_total",
]

COLUNAS_RANKING_TOTAL = [
    "cnpj",
    "itens_vencidos",
    "licitacoes_distintas",
    "valor_total",
]

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


def _sem_sentinelas(lf: pl.LazyFrame, coluna: str) -> pl.LazyFrame:
    return lf.filter(
        ~pl.col(coluna).is_in(CNPJ_SENTINELA) & ~pl.col(coluna).str.starts_with(PREFIXO_SENTINELA)
    )


def serie_fornecedor(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Agrega itens vencidos por competência e fornecedor.

    Alimenta o ranking filtrado por período. A granularidade por competência é
    o que permite ao endpoint recortar o intervalo sem recalcular nada.

    `valor_total` vai para Decimal(38, 4) porque `valor_item * quantidade`
    chega a 9,6e20 no dado real - 1.232 itens passam do limite de 18 dígitos.
    Somar em Decimal(18, 4) estouraria.
    """
    return (
        _sem_sentinelas(lf, "cnpj_vencedor")
        .group_by(["competencia", "cnpj_vencedor"])
        .agg(
            pl.len().alias("itens_vencidos"),
            pl.struct(CHAVE_NATURAL).n_unique().alias("licitacoes_distintas"),
            (
                pl.col("valor_item").cast(pl.Decimal(38, 4))
                * pl.col("quantidade").cast(pl.Decimal(38, 4))
            )
            .sum()
            .alias("valor_total"),
        )
        .rename({"cnpj_vencedor": "cnpj"})
    )


def ranking_fornecedor_total(serie: pl.LazyFrame) -> pl.LazyFrame:
    """Colapsa a série por competência num ranking global.

    Existe porque somar as 1,65 milhão de linhas da série em tempo de request
    custa 1.530 ms - 3x o orçamento -, e o ranking sem filtro de período é o
    que a tela de análise histórica abre por padrão. Aqui são 326 mil linhas.

    Recebe o resultado de `serie_fornecedor`, não os itens: derivar da série
    garante que os dois números fechem entre si.
    """
    return serie.group_by("cnpj").agg(
        pl.col("itens_vencidos").sum(),
        pl.col("licitacoes_distintas").sum(),
        pl.col("valor_total").sum(),
    )
