"""Parsers dos CSVs do Portal da Transparência.

Núcleo funcional: recebem bytes, devolvem DataFrame tipado. Não sabem de onde
vieram os bytes nem para onde vai o resultado.
"""

import io
import zipfile

import polars as pl

from tcc_jobs.core.competencia import Competencia

COLUNAS_LICITACAO = {
    "Número Licitação": "numero_licitacao",
    "Código UG": "codigo_ug",
    "Nome UG": "nome_ug",
    "Código Modalidade Compra": "codigo_modalidade",
    "Modalidade Compra": "modalidade",
    "Número Processo": "numero_processo",
    "Objeto": "objeto",
    "Situação Licitação": "situacao",
    "Código Órgão Superior": "codigo_orgao_superior",
    "Nome Órgão Superior": "nome_orgao_superior",
    "Código Órgão": "codigo_orgao",
    "Nome Órgão": "nome_orgao",
    "UF": "uf",
    "Município": "municipio",
    "Data Resultado Compra": "data_resultado",
    "Data Abertura": "data_abertura",
    "Valor Licitação": "valor",
}

# O CSV traz, em cada linha de licitação, atributos que pertencem às dimensões.
# O parser preserva todas as colunas; a carga é que distribui cada uma para a
# tabela correta:
#
#   codigo_modalidade, modalidade                 -> modalidade
#   codigo_ug, nome_ug, uf, municipio             -> unidade_gestora
#   codigo_orgao, nome_orgao, codigo_orgao_superior -> orgao
ESQUEMA_LICITACAO: dict[str, pl.DataType] = {
    "numero_licitacao": pl.String(),
    "codigo_ug": pl.String(),
    "nome_ug": pl.String(),
    "codigo_modalidade": pl.Int32(),
    "modalidade": pl.String(),
    "numero_processo": pl.String(),
    "objeto": pl.String(),
    "situacao": pl.String(),
    "codigo_orgao_superior": pl.String(),
    "nome_orgao_superior": pl.String(),
    "codigo_orgao": pl.String(),
    "nome_orgao": pl.String(),
    "uf": pl.String(),
    "municipio": pl.String(),
    "data_resultado": pl.Date(),
    "data_abertura": pl.Date(),
    "valor": pl.Decimal(18, 4),
    "competencia": pl.String(),
}


def extrair_do_zip(conteudo: bytes) -> dict[str, bytes]:
    """Devolve os CSVs do ZIP indexados pelo tipo, sem o prefixo de competência.

    Puro: opera sobre bytes em memória, sem tocar em disco.
    """
    arquivos: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(conteudo)) as zip_:
        for nome in zip_.namelist():
            # "202401_Licitação.csv" -> "Licitação"
            tipo = nome.split("_", 1)[1].removesuffix(".csv")
            arquivos[tipo] = zip_.read(nome)
    return arquivos


def _ler_csv(csv: bytes) -> pl.DataFrame:
    """Lê o CSV como texto puro, sem inferir tipos.

    O Polars aceita apenas utf8 e utf8-lossy - não existe opção latin-1, e o
    lossy corrompe os acentos inclusive nos nomes das colunas, fazendo
    "Nome Órgão Superior" virar "Nome �rg�o Superior" e deixar de ser
    encontrada. Por isso a decodificação acontece aqui, antes de o Polars ver
    os bytes.

    infer_schema_length=0 mantém tudo como string: a conversão de decimal e
    data é explícita, porque o formato brasileiro não é reconhecido.
    """
    texto = csv.decode("latin-1")
    return pl.read_csv(
        io.BytesIO(texto.encode("utf-8")),
        separator=";",
        infer_schema_length=0,
        truncate_ragged_lines=True,
    )


def _decimal(coluna: str) -> pl.Expr:
    """Converte decimal em formato brasileiro.

    Verificado no dado real: não há separador de milhar - o maior valor
    observado é 10665589,3300. Basta trocar a vírgula por ponto.
    """
    return pl.col(coluna).str.replace(",", ".").cast(pl.Decimal(18, 4), strict=False)


def _data(coluna: str) -> pl.Expr:
    """Converte DD/MM/AAAA.

    strict=False porque 16% das datas de abertura vêm vazias no dado real.
    """
    return pl.col(coluna).str.to_date("%d/%m/%Y", strict=False)


def parse_licitacao(csv: bytes, competencia: Competencia) -> pl.DataFrame:
    """CSV de licitação para DataFrame tipado, pronto para carga."""
    if not csv.strip():
        return pl.DataFrame(schema=ESQUEMA_LICITACAO)

    return (
        _ler_csv(csv)
        .rename(COLUNAS_LICITACAO)
        .with_columns(
            pl.col("codigo_modalidade").cast(pl.Int32, strict=False),
            _data("data_abertura"),
            _data("data_resultado"),
            _decimal("valor"),
            pl.lit(str(competencia)).alias("competencia"),
        )
        .select(list(ESQUEMA_LICITACAO))
    )
