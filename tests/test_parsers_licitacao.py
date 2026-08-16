from datetime import date
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from tcc_jobs.core.competencia import Competencia
from tcc_jobs.etl.parsers import extrair_do_zip, parse_licitacao

FIXTURE = Path(__file__).parent / "fixtures" / "202401_amostra.zip"
C = Competencia.de_str("202401")


@pytest.fixture
def arquivos() -> dict[str, bytes]:
    return extrair_do_zip(FIXTURE.read_bytes())


def test_extrai_os_quatro_csvs(arquivos: dict[str, bytes]) -> None:
    assert set(arquivos) == {
        "Licitação",
        "ItemLicitação",
        "ParticipantesLicitação",
        "EmpenhosRelacionados",
    }


def test_preserva_acentuacao_do_latin1(arquivos: dict[str, bytes]) -> None:
    """O Polars aceita apenas utf8 e utf8-lossy, e o lossy corrompe até o nome
    das colunas. A decodificação precisa vir antes."""
    df = parse_licitacao(arquivos["Licitação"], C)

    nomes = df["nome_orgao_superior"].to_list()
    assert any("Ministério" in n for n in nomes if n)
    assert not any("�" in n for n in nomes if n)


def test_converte_decimal_com_virgula(arquivos: dict[str, bytes]) -> None:
    """Sem separador de milhar: o maior valor observado é 10665589,3300."""
    df = parse_licitacao(arquivos["Licitação"], C)

    assert df.schema["valor"] == pl.Decimal(18, 4)
    assert df["valor"][0] == Decimal("170612.0000")


def test_converte_data_no_formato_brasileiro(arquivos: dict[str, bytes]) -> None:
    df = parse_licitacao(arquivos["Licitação"], C)

    assert df.schema["data_abertura"] == pl.Date
    assert df["data_abertura"][0] == date(2023, 12, 26)


def test_tolera_data_de_abertura_vazia(arquivos: dict[str, bytes]) -> None:
    """16% das linhas do dado real vêm sem data de abertura."""
    df = parse_licitacao(arquivos["Licitação"], C)

    assert df["data_abertura"].is_null().sum() > 0


def test_acrescenta_a_competencia_de_origem(arquivos: dict[str, bytes]) -> None:
    df = parse_licitacao(arquivos["Licitação"], C)

    assert df["competencia"].unique().to_list() == ["202401"]


def test_colunas_da_chave_natural_presentes(arquivos: dict[str, bytes]) -> None:
    df = parse_licitacao(arquivos["Licitação"], C)

    assert {"numero_licitacao", "codigo_ug", "codigo_modalidade"} <= set(df.columns)
    assert df.schema["codigo_modalidade"] == pl.Int32


def test_preserva_colunas_das_dimensoes(arquivos: dict[str, bytes]) -> None:
    """O parser não distribui - a carga é que separa cada coluna para a tabela
    correta. Ver as decisões de modelagem."""
    df = parse_licitacao(arquivos["Licitação"], C)

    esperadas = {"modalidade", "uf", "municipio", "nome_ug", "nome_orgao_superior"}
    assert esperadas <= set(df.columns)


def test_arquivo_vazio_devolve_dataframe_vazio_com_esquema() -> None:
    """EmpenhosRelacionados pode ter zero linhas - é caso normal, não erro."""
    df = parse_licitacao(b"", C)

    assert df.height == 0
    assert "numero_licitacao" in df.columns
