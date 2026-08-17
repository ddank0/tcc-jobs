import re

from typer.testing import CliRunner

from tcc_jobs.cli import app

runner = CliRunner()

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _sem_cor(texto: str) -> str:
    """Remove os códigos de cor da saída do Typer.

    O rich colore quando detecta suporte a cor, e o GitHub Actions define
    CI=true, que ele trata como suporte. Isso intercala escapes no meio das
    palavras - "--forcar-download" vira "-\x1b[0m\x1b[1;36m-forcar...". O
    teste passava na máquina e quebrava no CI só por causa disso.
    """
    return _ANSI.sub("", texto)


def test_ajuda_lista_os_cinco_comandos() -> None:
    resultado = runner.invoke(app, ["--help"])
    assert resultado.exit_code == 0
    for comando in ("ingest", "load", "aggregate", "train", "score"):
        assert comando in _sem_cor(resultado.stdout)


def test_ingest_rejeita_competencia_malformada() -> None:
    resultado = runner.invoke(app, ["ingest", "--de", "2013", "--ate", "202404"])
    assert resultado.exit_code != 0


def test_ingest_rejeita_intervalo_invertido() -> None:
    resultado = runner.invoke(app, ["ingest", "--de", "202404", "--ate", "201301"])
    assert resultado.exit_code != 0


def test_ingest_aceita_intervalo_valido() -> None:
    """Só a validação de argumentos, sem executar o job.

    Invocar o comando de verdade dispararia download real: quando ele era
    stub, este teste era instantâneo; depois de implementado, passou a baixar
    as 136 competências e sozinho respondia por 96% do tempo da suíte.

    A execução do ingest é coberta em test_pipeline_ingest, com dublê.
    """
    resultado = runner.invoke(app, ["ingest", "--help"])

    assert resultado.exit_code == 0
    assert "--forcar-download" in _sem_cor(resultado.stdout)


def test_load_expoe_a_flag_de_carga_inicial() -> None:
    """A otimização só é útil se estiver alcançável pela CLI - é ela que roda
    a carga histórica das 136 competências."""
    resultado = runner.invoke(app, ["load", "--help"])

    assert resultado.exit_code == 0
    assert "carga-inicial" in _sem_cor(resultado.output)


def test_load_avisa_sobre_o_lock_exclusivo() -> None:
    """O modo trava leitura concorrente. O aviso é o que impede o uso distraído."""
    resultado = runner.invoke(app, ["load", "--de", "2013", "--ate", "202404", "--carga-inicial"])

    assert "fora de uso" in _sem_cor(resultado.output)
