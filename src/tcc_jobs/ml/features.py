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


CHAVE = ["numero_licitacao", "codigo_ug", "codigo_modalidade"]

# Contrato da matriz: as colunas além da chave. A tela de contribuição e o
# features_json persistido usam exatamente estes nomes - vocabulário neutro
# por requisito de produto.
COLUNAS_FEATURES = [
    "razao_valor_grupo",
    "razao_participantes_modalidade",
    "taxa_vitoria_vencedor",
    "hhi_orgao",
    "razao_item_max",
    "desvio_sazonal_orgao",
    "sem_vencedor",
    "contem_item_implausivel",
]

# Grupos (órgão, modalidade) com menos licitações que isto usam a mediana da
# modalidade como referência de valor: 34% dos grupos reais são menores, mas
# cobrem só 0,2% das licitações.
MINIMO_GRUPO = 30

# CNPJs que a fonte usa como marcador, não como identidade: -11 é "Sigiloso",
# -2 é "Inválido", ESTRANG* é estrangeiro sem CNPJ. Contam como participantes
# (existem), mas não alimentam atributo que depende de QUEM é - encontrado na
# análise qualitativa: o -11 como "vencedor" recorrente dava HHI 0,976 às
# licitações sigilosas da Polícia Federal, artefato puro de representação.
CNPJ_SENTINELA = ["-11", "-2"]
PREFIXO_SENTINELA = "ESTRANG"


def montar_features(
    licitacoes: pl.LazyFrame,
    itens: pl.LazyFrame,
    participantes: pl.LazyFrame,
) -> pl.LazyFrame:
    """Uma linha por licitação, com os atributos de atipicidade.

    Tudo contextualizado: 70,3% das licitações têm participante único - a
    natureza de Dispensa e Inexigibilidade (98%), mas exceção em Pregão
    (6-11%). Atributo absoluto apontaria o rito, não o desvio; as razões são
    sempre relativas ao grupo ou à modalidade.

    `data_abertura` não entra em nada: 72,6% nula no dado real.
    """
    base = licitacoes.select(CHAVE + ["codigo_orgao", "competencia", "valor"]).unique(subset=CHAVE)

    # --- valor relativo ao grupo, com fallback para a modalidade ---
    grupo = base.group_by(["codigo_orgao", "codigo_modalidade"]).agg(
        pl.col("valor").median().alias("mediana_grupo"),
        pl.len().alias("n_grupo"),
    )
    modalidade_val = base.group_by("codigo_modalidade").agg(
        pl.col("valor").median().alias("mediana_modalidade")
    )
    base = (
        base.join(grupo, on=["codigo_orgao", "codigo_modalidade"], how="left")
        .join(modalidade_val, on="codigo_modalidade", how="left")
        .with_columns(
            pl.when(pl.col("n_grupo") >= MINIMO_GRUPO)
            .then(pl.col("mediana_grupo"))
            .otherwise(pl.col("mediana_modalidade"))
            .alias("mediana_ref")
        )
        .with_columns(
            pl.when(pl.col("valor").is_not_null() & (pl.col("mediana_ref") > 0))
            .then(pl.col("valor") / pl.col("mediana_ref"))
            .otherwise(None)
            .cast(pl.Float64)
            .alias("razao_valor_grupo")
        )
    )

    # --- participação, sempre pela fonte de verdade (flag_vencedor) ---
    por_lic = participantes.group_by(CHAVE).agg(
        pl.col("cnpj_participante").n_unique().alias("n_participantes"),
        pl.col("cnpj_participante")
        .filter(
            pl.col("flag_vencedor")
            & ~pl.col("cnpj_participante").is_in(CNPJ_SENTINELA)
            & ~pl.col("cnpj_participante").str.starts_with(PREFIXO_SENTINELA)
        )
        .first()
        .alias("cnpj_vencedor"),
        pl.col("flag_vencedor").sum().alias("n_vencedores"),
    )
    mediana_mod = (
        por_lic.join(base.select(CHAVE).unique(subset=CHAVE), on=CHAVE, how="inner")
        .group_by("codigo_modalidade")
        .agg(pl.col("n_participantes").median().alias("mediana_part_modalidade"))
    )

    # taxa de vitória do vencedor naquele órgão e HHI do órgão - só com
    # identidade real: sentinela fora
    disputas = participantes.filter(
        ~pl.col("cnpj_participante").is_in(CNPJ_SENTINELA)
        & ~pl.col("cnpj_participante").str.starts_with(PREFIXO_SENTINELA)
    ).join(base.select(CHAVE + ["codigo_orgao"]), on=CHAVE, how="inner")
    taxa = disputas.group_by(["codigo_orgao", "cnpj_participante"]).agg(
        pl.col("flag_vencedor").mean().cast(pl.Float64).alias("taxa_vitoria"),
    )
    vitorias_orgao = (
        disputas.filter(pl.col("flag_vencedor"))
        .group_by(["codigo_orgao", "cnpj_participante"])
        .agg(pl.len().alias("vitorias"))
    )
    hhi = vitorias_orgao.group_by("codigo_orgao").agg(
        ((pl.col("vitorias") / pl.col("vitorias").sum()) ** 2).sum().alias("hhi_orgao")
    )

    # --- itens: razão unitária só com itens plausíveis ---
    marcados = marcar_plausibilidade(itens)
    mediana_item = (
        marcados.filter(pl.col("plausivel") & (pl.col("valor_item") > 0))
        .group_by("codigo_item_compra")
        .agg(pl.col("valor_item").median().alias("mediana_item"))
    )
    razao_item = (
        marcados.filter(pl.col("plausivel"))
        .join(mediana_item, on="codigo_item_compra", how="left")
        .with_columns(
            pl.when(pl.col("mediana_item") > 0)
            .then(pl.col("valor_item") / pl.col("mediana_item"))
            .otherwise(None)
            .cast(pl.Float64)
            .alias("razao")
        )
        .group_by(CHAVE)
        .agg(pl.col("razao").max().alias("razao_item_max"))
    )
    implausivel = marcados.group_by(CHAVE).agg(
        (~pl.col("plausivel")).any().alias("contem_item_implausivel")
    )

    # --- desvio sazonal do órgão: participação da competência no ano típico ---
    mensal = base.group_by(["codigo_orgao", "competencia"]).agg(pl.len().alias("n_mes"))
    mensal = mensal.with_columns(pl.col("competencia").str.slice(4, 2).alias("mes"))
    tipico = mensal.group_by(["codigo_orgao", "mes"]).agg(
        pl.col("n_mes").median().alias("mediana_mes")
    )
    sazonal = (
        mensal.join(tipico, on=["codigo_orgao", "mes"], how="left")
        .with_columns(
            pl.when(pl.col("mediana_mes") > 0)
            .then(pl.col("n_mes") / pl.col("mediana_mes"))
            .otherwise(None)
            .cast(pl.Float64)
            .alias("desvio_sazonal_orgao")
        )
        .select(["codigo_orgao", "competencia", "desvio_sazonal_orgao"])
    )

    return (
        base.join(por_lic, on=CHAVE, how="left")
        .join(mediana_mod, on="codigo_modalidade", how="left")
        .with_columns(
            pl.when(pl.col("mediana_part_modalidade") > 0)
            .then(pl.col("n_participantes") / pl.col("mediana_part_modalidade"))
            .otherwise(None)
            .cast(pl.Float64)
            .alias("razao_participantes_modalidade"),
            # sem_vencedor: teve participante e ninguém venceu (0,7% do real).
            # Licitação sem participante nenhum fica False - a ausência é
            # outra informação, capturada pelo nulo em razao_participantes.
            (pl.col("n_vencedores").fill_null(1) == 0).alias("sem_vencedor"),
        )
        .join(
            taxa.rename({"cnpj_participante": "cnpj_vencedor"}),
            left_on=["codigo_orgao", "cnpj_vencedor"],
            right_on=["codigo_orgao", "cnpj_vencedor"],
            how="left",
        )
        .rename({"taxa_vitoria": "taxa_vitoria_vencedor"})
        .join(hhi, on="codigo_orgao", how="left")
        .join(razao_item, on=CHAVE, how="left")
        .join(implausivel, on=CHAVE, how="left")
        .join(sazonal, on=["codigo_orgao", "competencia"], how="left")
        .with_columns(pl.col("contem_item_implausivel").fill_null(False))
        .select(CHAVE + COLUNAS_FEATURES)
    )
