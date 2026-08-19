"""Matriz de atributos para a detecção de atipicidade. Núcleo funcional.

Não importa db/ nem portal/; a casca que lê silver e banco fica em runner.py.
"""

import polars as pl

# Produto quantidade x valor_item acima disto é tratado como erro de
# preenchimento da fonte, não como contratação atípica. Medido no dado real:
# 2,06% dos itens passam de R$ 1 bilhão, com extremo de R$ 9,6 quatrilhões
# num único item - dois bilhões de unidades de um convênio médico, o valor
# total lançado no campo de quantidade. Um detector treinado com esses pontos
# no espaço de features aponta digitação, não padrão de contratação - por
# isso a separação vem ANTES do modelo: implausível e atípico são classes
# distintas, e o corte é declarado em vez de embutido.
CORTE_PLAUSIBILIDADE = 1_000_000_000  # R$ 1 bilhão por item


def marcar_plausibilidade(itens: pl.LazyFrame) -> pl.LazyFrame:
    """Adiciona a coluna `plausivel` aos itens.

    O corte é por item, não por licitação: a licitação que contém um item
    implausível mantém os demais, e ganha uma flag booleana na matriz de
    features em vez de ser descartada.

    Nulo é plausível: ausência de dado não é erro de preenchimento, e o
    tratamento de nulo pertence às features.
    """
    produto = pl.col("quantidade") * pl.col("valor_item")
    return itens.with_columns(
        (produto.is_null() | (produto <= CORTE_PLAUSIBILIDADE)).alias("plausivel")
    )
