import pytest
from typer.testing import CliRunner

from tcc_jobs.cli import app, validar_competencia

runner = CliRunner()


def test_ajuda_lista_os_cinco_comandos():
    resultado = runner.invoke(app, ["--help"])
    assert resultado.exit_code == 0
    for comando in ("ingest", "load", "aggregate", "train", "score"):
        assert comando in resultado.stdout


@pytest.mark.parametrize("valor", ["201301", "202404", "199912"])
def test_competencia_valida(valor):
    assert validar_competencia(valor) == valor


@pytest.mark.parametrize("valor", ["2013", "20130", "2013-01", "201313", "201300", "abcdef"])
def test_competencia_invalida(valor):
    with pytest.raises(ValueError, match="competência"):
        validar_competencia(valor)


def test_ingest_rejeita_competencia_malformada():
    resultado = runner.invoke(app, ["ingest", "--de", "2013", "--ate", "202404"])
    assert resultado.exit_code != 0


def test_ingest_rejeita_intervalo_invertido():
    resultado = runner.invoke(app, ["ingest", "--de", "202404", "--ate", "201301"])
    assert resultado.exit_code != 0


def test_ingest_aceita_intervalo_valido():
    resultado = runner.invoke(app, ["ingest", "--de", "201301", "--ate", "202404"])
    assert resultado.exit_code == 0
