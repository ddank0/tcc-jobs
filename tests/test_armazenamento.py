from pathlib import Path

import polars as pl

from tcc_jobs.core.competencia import Competencia
from tcc_jobs.etl.armazenamento import Armazenamento

C = Competencia.de_str("202401")


def test_grava_e_le_bronze(tmp_path: Path) -> None:
    arm = Armazenamento(tmp_path)

    caminho = arm.gravar_bronze(C, b"conteudo-zip")

    assert caminho.exists()
    assert arm.ler_bronze(C) == b"conteudo-zip"


def test_bronze_ausente_devolve_none(tmp_path: Path) -> None:
    assert Armazenamento(tmp_path).ler_bronze(C) is None


def test_regravar_bronze_sobrescreve(tmp_path: Path) -> None:
    """Bronze nunca é transformado, mas pode ser rebaixado da fonte."""
    arm = Armazenamento(tmp_path)
    arm.gravar_bronze(C, b"primeiro")
    arm.gravar_bronze(C, b"segundo")

    assert arm.ler_bronze(C) == b"segundo"


def test_grava_silver_em_parquet(tmp_path: Path) -> None:
    arm = Armazenamento(tmp_path)
    df = pl.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})

    caminho = arm.gravar_silver(C, "licitacao", df)

    assert caminho.suffix == ".parquet"
    assert pl.read_parquet(caminho).equals(df)


def test_silver_separa_por_tabela_e_competencia(tmp_path: Path) -> None:
    arm = Armazenamento(tmp_path)

    c1 = arm.caminho_silver(C, "licitacao")
    c2 = arm.caminho_silver(Competencia.de_str("202402"), "licitacao")
    c3 = arm.caminho_silver(C, "participante")

    assert len({c1, c2, c3}) == 3
    assert "licitacao" in str(c1.parent)


def test_parquet_comprime(tmp_path: Path) -> None:
    """O ganho vem da compressão colunar: os CSVs repetem CNPJ e nome de
    empresa milhares de vezes."""
    arm = Armazenamento(tmp_path)
    df = pl.DataFrame({"cnpj": ["14986916000177"] * 10_000})

    caminho = arm.gravar_silver(C, "participante", df)

    assert caminho.stat().st_size < 10_000


def test_silver_preserva_tipos(tmp_path: Path) -> None:
    """Parquet guarda o esquema; se os tipos se perdessem, a carga via COPY
    falharia com dado convertido errado."""
    from datetime import date
    from decimal import Decimal

    arm = Armazenamento(tmp_path)
    df = pl.DataFrame(
        {
            "valor": [Decimal("170612.0000")],
            "data_abertura": [date(2023, 12, 26)],
            "flag": [True],
        },
        schema={"valor": pl.Decimal(18, 4), "data_abertura": pl.Date, "flag": pl.Boolean},
    )

    lido = pl.read_parquet(arm.gravar_silver(C, "licitacao", df))

    assert lido.schema == df.schema
    assert lido["valor"][0] == Decimal("170612.0000")
