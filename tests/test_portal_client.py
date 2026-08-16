from collections.abc import Callable

import httpx
import pytest

from tcc_jobs.core.competencia import Competencia
from tcc_jobs.portal.client import (
    URL_BASE,
    ClienteHttpPortal,
    CompetenciaIndisponivelError,
)

C = Competencia.de_str("202401")

Handler = Callable[[httpx.Request], httpx.Response]


def _cliente(handler: Handler) -> ClienteHttpPortal:
    """Cliente com transporte falso: nenhum teste toca a rede."""
    return ClienteHttpPortal(transporte=httpx.MockTransport(handler))


def test_monta_a_url_com_a_competencia() -> None:
    vistas: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        vistas.append(str(request.url))
        return httpx.Response(200, content=b"conteudo-zip")

    assert _cliente(handler).baixar(C) == b"conteudo-zip"
    assert vistas == [f"{URL_BASE}/202401"]


def test_403_significa_competencia_fora_da_janela() -> None:
    """De 202405 em diante a fonte devolve 403: foi descontinuada."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, content=b"<Error>AccessDenied</Error>")

    with pytest.raises(CompetenciaIndisponivelError, match="202405"):
        _cliente(handler).baixar(Competencia.de_str("202405"))


def test_erro_de_servidor_propaga() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    with pytest.raises(httpx.HTTPStatusError):
        _cliente(handler).baixar(C)


def test_segue_redirecionamento() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/202401"):
            return httpx.Response(302, headers={"Location": "https://exemplo/arquivo.zip"})
        return httpx.Response(200, content=b"zip-final")

    assert _cliente(handler).baixar(C) == b"zip-final"
