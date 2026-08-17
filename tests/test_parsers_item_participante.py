from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from tcc_jobs.etl.parsers import extrair_do_zip, parse_item, parse_participante

FIXTURE = Path(__file__).parent / "fixtures" / "202401_amostra.zip"


@pytest.fixture
def arquivos() -> dict[str, bytes]:
    return extrair_do_zip(FIXTURE.read_bytes())


def test_item_converte_valor_e_quantidade(arquivos: dict[str, bytes]) -> None:
    df = parse_item(arquivos["ItemLicitação"])

    assert df.schema["valor_item"] == pl.Decimal(18, 4)
    assert df.schema["quantidade"] == pl.Decimal(18, 4)
    assert df["valor_item"][0] == Decimal("99500.0000")


def test_item_traz_a_chave_natural_e_o_vencedor(arquivos: dict[str, bytes]) -> None:
    df = parse_item(arquivos["ItemLicitação"])

    assert {"numero_licitacao", "codigo_ug", "codigo_modalidade"} <= set(df.columns)
    assert df["cnpj_vencedor"][0] == "24426491000103"


def test_participante_converte_flag_para_booleano(arquivos: dict[str, bytes]) -> None:
    """Flag Vencedor vem como SIM/NÃO, com acento em latin-1."""
    df = parse_participante(arquivos["ParticipantesLicitação"])

    assert df.schema["flag_vencedor"] == pl.Boolean
    # Contagem exata, não "é booleano": a fixture tem 13 SIM e 17 NÃO. Uma
    # conversão que devolvesse constante - ou que invertesse SIM e NÃO -
    # passaria por qualquer asserção mais frouxa que esta, e é esta coluna que
    # sustenta todos os atributos de competitividade.
    assert df["flag_vencedor"].sum() == 13
    assert (~df["flag_vencedor"]).sum() == 17


def test_participante_reconhece_o_vencedor(arquivos: dict[str, bytes]) -> None:
    """Se a conversão SIM/NÃO falhasse, todos viriam False e o erro passaria
    despercebido - é esta coluna que sustenta os atributos de competitividade."""
    df = parse_participante(arquivos["ParticipantesLicitação"])

    assert df["flag_vencedor"].sum() == 13
    assert not df["flag_vencedor"].all(), "nem todos podem ser vencedores"


def test_participante_preserva_nome_com_acento(arquivos: dict[str, bytes]) -> None:
    df = parse_participante(arquivos["ParticipantesLicitação"])

    assert not any("�" in n for n in df["nome_participante"].to_list() if n)


def test_participante_traz_cnpj(arquivos: dict[str, bytes]) -> None:
    df = parse_participante(arquivos["ParticipantesLicitação"])

    assert df["cnpj_participante"][0] == "14986916000177"


def test_arquivo_vazio_nao_e_erro() -> None:
    """EmpenhosRelacionados vem sem linhas em algumas competências."""
    assert parse_item(b"").height == 0
    assert parse_participante(b"").height == 0


def test_csv_com_cabecalho_e_sem_linhas(arquivos: dict[str, bytes]) -> None:
    """Caso real e diferente de bytes vazios: EmpenhosRelacionados vem com 189
    bytes de cabeçalho e zero linhas de dados, então `not csv.strip()` é falso
    e o parser precisa processar normalmente."""
    cabecalho = arquivos["ItemLicitação"].split(b"\r\n")[0] + b"\r\n"

    df = parse_item(cabecalho)

    assert df.height == 0
    assert list(df.columns) == list(parse_item(b"").columns)


def test_esquema_do_vazio_bate_com_o_preenchido(arquivos: dict[str, bytes]) -> None:
    """A carga usa as mesmas colunas nos dois casos; divergência quebraria o
    COPY só quando aparecesse uma competência sem itens."""
    assert parse_item(b"").schema == parse_item(arquivos["ItemLicitação"]).schema
    assert (
        parse_participante(b"").schema
        == parse_participante(arquivos["ParticipantesLicitação"]).schema
    )
