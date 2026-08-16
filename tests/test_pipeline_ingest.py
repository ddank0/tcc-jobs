from pathlib import Path

from tcc_jobs.core.competencia import Competencia
from tcc_jobs.etl.armazenamento import Armazenamento
from tcc_jobs.etl.pipeline import ingerir
from tests.conftest import CriarCliente

C = Competencia.de_str("202401")


def test_grava_bronze_e_silver(tmp_path: Path, criar_cliente: CriarCliente) -> None:
    arm = Armazenamento(tmp_path)
    cliente = criar_cliente()

    resultados = ingerir([C], cliente, arm)

    assert len(resultados) == 1
    assert arm.ler_bronze(C) is not None
    for tabela in ("licitacao", "item", "participante"):
        assert arm.caminho_silver(C, tabela).exists()


def test_conta_linhas_por_tabela(tmp_path: Path, criar_cliente: CriarCliente) -> None:
    cliente = criar_cliente()

    resultado = ingerir([C], cliente, Armazenamento(tmp_path))[0]

    assert resultado.linhas_por_tabela["licitacao"] > 0
    assert resultado.linhas_por_tabela["participante"] > 0
    assert resultado.erro is None


def test_reaproveita_bronze_existente(tmp_path: Path, criar_cliente: CriarCliente) -> None:
    """Reprocessar não deve rebaixar: bronze é a fonte de reprocessamento."""
    arm = Armazenamento(tmp_path)
    cliente = criar_cliente()

    ingerir([C], cliente, arm)
    resultado = ingerir([C], cliente, arm)[0]

    assert cliente.chamadas == ["202401"]
    assert resultado.veio_do_cache is True


def test_forcar_download_ignora_o_cache(tmp_path: Path, criar_cliente: CriarCliente) -> None:
    arm = Armazenamento(tmp_path)
    cliente = criar_cliente()

    ingerir([C], cliente, arm)
    ingerir([C], cliente, arm, forcar_download=True)

    assert cliente.chamadas == ["202401", "202401"]


def test_competencia_indisponivel_nao_interrompe_as_outras(
    tmp_path: Path, criar_cliente: CriarCliente
) -> None:
    """De 202405 em diante a fonte devolve 403. É o fim da janela, não falha."""
    arm = Armazenamento(tmp_path)
    cliente = criar_cliente(indisponiveis={"202405"})
    janela = [C, Competencia.de_str("202405")]

    resultados = ingerir(janela, cliente, arm)

    assert resultados[0].erro is None
    assert resultados[1].erro is not None
    assert "indisponível" in resultados[1].erro


def test_erro_inesperado_nao_derruba_o_lote(tmp_path: Path, criar_cliente: CriarCliente) -> None:
    """ZIP corrompido em uma competência não pode abortar as demais."""
    arm = Armazenamento(tmp_path)
    cliente = criar_cliente(conteudo=b"isto-nao-e-um-zip")

    resultado = ingerir([C], cliente, arm)[0]

    assert resultado.erro is not None
    assert resultado.linhas_por_tabela == {}


def test_reprocessa_varias_competencias(tmp_path: Path, criar_cliente: CriarCliente) -> None:
    arm = Armazenamento(tmp_path)
    cliente = criar_cliente()
    janela = Competencia.intervalo(Competencia.de_str("202401"), Competencia.de_str("202403"))

    resultados = ingerir(janela, cliente, arm)

    assert len(resultados) == 3
    assert cliente.chamadas == ["202401", "202402", "202403"]
    assert all(r.erro is None for r in resultados)
