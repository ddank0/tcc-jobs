"""Parsers dos CSVs do Portal da Transparência.

Núcleo funcional: recebem bytes, devolvem DataFrame tipado. Não sabem de onde
vieram os bytes nem para onde vai o resultado.
"""

import io
import struct
import zipfile
import zlib

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


def zip_integro(conteudo: bytes) -> bool:
    """O conteúdo é um ZIP completo e legível?

    Um download interrompido ainda começa com a assinatura `PK`, então checar
    o cabeçalho não basta - é preciso ler o índice central, que fica no fim do
    arquivo. Foi assim que a competência 201812 entrou em bronze com exatos
    8 MiB e passou a ser servida pelo cache indefinidamente.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as zip_:
            return zip_.testzip() is None
    except zipfile.BadZipFile, OSError:
        return False


def extrair_do_zip(conteudo: bytes) -> dict[str, bytes]:
    """Devolve os CSVs do ZIP indexados pelo tipo, sem o prefixo de competência.

    Puro: opera sobre bytes em memória, sem tocar em disco.
    """
    arquivos: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(conteudo)) as zip_:
        for nome in zip_.namelist():
            arquivos[_tipo_do_membro(nome)] = zip_.read(nome)
    return arquivos


# Deslocamentos dentro do cabeçalho local de um membro, conforme o formato ZIP.
_ASSINATURA_LOCAL = b"PK\x03\x04"
_CABECALHO_LOCAL = 30
_DEFLATE = 8


def _tipo_do_membro(nome: str) -> str:
    """ "202401_Licitação.csv" -> "Licitação"."""
    return nome.split("_", 1)[1].removesuffix(".csv")


def extrair_recuperavel(conteudo: bytes) -> dict[str, bytes]:
    """Extrai o que der de um ZIP truncado, varrendo os cabeçalhos locais.

    O `zipfile` depende do índice central, que fica no fim do arquivo - se o
    fim foi cortado, ele não abre nada, nem os membros intactos do começo.
    Aqui a varredura é para a frente, membro a membro, e só entra no resultado
    o que descomprimir exatamente até o tamanho declarado.

    Existe por causa da competência 201812, publicada corrompida na origem: o
    ZIP termina em exatos 8 MiB, no meio do último CSV. Descartar a
    competência inteira abriria um buraco na série mensal - e séries com
    buraco são um problema para o SARIMA, que pressupõe espaçamento regular.

    Um membro parcial nunca é devolvido. Meio CSV de participantes seria pior
    que nenhum: enviesaria as features de competitividade para baixo sem
    deixar sinal de que faltou dado.
    """
    recuperados: dict[str, bytes] = {}
    posicao = conteudo.find(_ASSINATURA_LOCAL)

    while posicao >= 0:
        try:
            (metodo,) = struct.unpack_from("<H", conteudo, posicao + 8)
            comprimido, original = struct.unpack_from("<II", conteudo, posicao + 18)
            tam_nome, tam_extra = struct.unpack_from("<HH", conteudo, posicao + 26)
            nome = conteudo[posicao + _CABECALHO_LOCAL : posicao + _CABECALHO_LOCAL + tam_nome]
            inicio = posicao + _CABECALHO_LOCAL + tam_nome + tam_extra
            bruto = conteudo[inicio : inicio + comprimido]

            if metodo == _DEFLATE:
                dados = zlib.decompressobj(-zlib.MAX_WBITS).decompress(bruto)
            else:
                dados = bruto

            if len(dados) == original:
                recuperados[_tipo_do_membro(nome.decode("utf-8", "replace"))] = dados

        except struct.error, zlib.error, IndexError, UnicodeDecodeError:
            pass  # membro ilegível não impede os seguintes

        posicao = conteudo.find(_ASSINATURA_LOCAL, posicao + len(_ASSINATURA_LOCAL))

    return recuperados


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


COLUNAS_ITEM = {
    "Número Licitação": "numero_licitacao",
    "Código UG": "codigo_ug",
    "Código Modalidade Compra": "codigo_modalidade",
    "Código Item Compra": "codigo_item_compra",
    "Descrição": "descricao",
    "Quantidade Item": "quantidade",
    "Valor Item": "valor_item",
    "Código Vencedor": "cnpj_vencedor",
    "Nome Vencedor": "nome_vencedor",
}

COLUNAS_PARTICIPANTE = {
    "Número Licitação": "numero_licitacao",
    "Código UG": "codigo_ug",
    "Código Modalidade Compra": "codigo_modalidade",
    "Código Item Compra": "codigo_item_compra",
    "Código Participante": "cnpj_participante",
    "Nome Participante": "nome_participante",
    "Flag Vencedor": "flag_vencedor",
}

ESQUEMA_ITEM: dict[str, pl.DataType] = {
    "numero_licitacao": pl.String(),
    "codigo_ug": pl.String(),
    "codigo_modalidade": pl.Int32(),
    "codigo_item_compra": pl.String(),
    "descricao": pl.String(),
    "quantidade": pl.Decimal(18, 4),
    "valor_item": pl.Decimal(18, 4),
    "cnpj_vencedor": pl.String(),
    "nome_vencedor": pl.String(),
}

ESQUEMA_PARTICIPANTE: dict[str, pl.DataType] = {
    "numero_licitacao": pl.String(),
    "codigo_ug": pl.String(),
    "codigo_modalidade": pl.Int32(),
    "codigo_item_compra": pl.String(),
    "cnpj_participante": pl.String(),
    "nome_participante": pl.String(),
    "flag_vencedor": pl.Boolean(),
}


def parse_item(csv: bytes) -> pl.DataFrame:
    """CSV de itens licitados para DataFrame tipado.

    cnpj_vencedor é mantido apesar de derivável de participante: as duas
    fontes divergem em ~30 casos por competência, e descartar uma perderia
    informação. Para features de competitividade, a fonte de verdade é
    participante.flag_vencedor.
    """
    if not csv.strip():
        return pl.DataFrame(schema=ESQUEMA_ITEM)

    return (
        _ler_csv(csv)
        .rename(COLUNAS_ITEM)
        .with_columns(
            pl.col("codigo_modalidade").cast(pl.Int32, strict=False),
            _decimal("quantidade"),
            _decimal("valor_item"),
        )
        .select(list(ESQUEMA_ITEM))
    )


def parse_participante(csv: bytes) -> pl.DataFrame:
    """CSV de participantes para DataFrame tipado.

    É o arquivo mais valioso da fonte: o conjunto de concorrentes por item,
    com identificação do vencedor, é o que habilita os atributos de
    competitividade da detecção de anomalias.

    Flag Vencedor vem como SIM/NÃO - com acento, o que reforça a necessidade
    de decodificar latin-1 antes do Polars.
    """
    if not csv.strip():
        return pl.DataFrame(schema=ESQUEMA_PARTICIPANTE)

    return (
        _ler_csv(csv)
        .rename(COLUNAS_PARTICIPANTE)
        .with_columns(
            pl.col("codigo_modalidade").cast(pl.Int32, strict=False),
            (pl.col("flag_vencedor").str.strip_chars() == "SIM").alias("flag_vencedor"),
        )
        .select(list(ESQUEMA_PARTICIPANTE))
    )
