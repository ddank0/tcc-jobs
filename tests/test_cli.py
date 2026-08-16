from typer.testing import CliRunner

from tcc_jobs.cli import app

runner = CliRunner()


def test_ajuda_lista_os_cinco_comandos() -> None:
    resultado = runner.invoke(app, ["--help"])
    assert resultado.exit_code == 0
    for comando in ("ingest", "load", "aggregate", "train", "score"):
        assert comando in resultado.stdout


def test_ingest_rejeita_competencia_malformada() -> None:
    resultado = runner.invoke(app, ["ingest", "--de", "2013", "--ate", "202404"])
    assert resultado.exit_code != 0


def test_ingest_rejeita_intervalo_invertido() -> None:
    resultado = runner.invoke(app, ["ingest", "--de", "202404", "--ate", "201301"])
    assert resultado.exit_code != 0


def test_ingest_aceita_intervalo_valido() -> None:
    resultado = runner.invoke(app, ["ingest", "--de", "201301", "--ate", "202404"])
    assert resultado.exit_code == 0
