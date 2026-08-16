from typing import Protocol

import httpx

from tcc_jobs.core.competencia import Competencia

URL_BASE = "https://portaldatransparencia.gov.br/download-de-dados/licitacoes"

HTTP_403_FORBIDDEN = 403


class CompetenciaIndisponivelError(Exception):
    """A fonte não publica esta competência.

    De 202405 em diante o Portal devolve 403: a base foi descontinuada com a
    transição para a Lei 14.133/2021. Não é falha do job - é o fim da janela.
    """


class ClientePortal(Protocol):
    """Fronteira de I/O com a fonte de dados.

    Existe para que o pipeline seja testável sem rede.
    """

    def baixar(self, competencia: Competencia) -> bytes: ...


class ClienteHttpPortal:
    """Implementação sobre httpx, seguindo redirecionamento."""

    def __init__(
        self,
        url_base: str = URL_BASE,
        timeout: float = 120.0,
        transporte: httpx.BaseTransport | None = None,
    ) -> None:
        self._url_base = url_base
        self._cliente = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            transport=transporte,
        )

    def baixar(self, competencia: Competencia) -> bytes:
        resposta = self._cliente.get(f"{self._url_base}/{competencia}")

        # Literal em vez de httpx.codes.FORBIDDEN: o enum do httpx é declarado
        # como (código, frase), e o Pyright acusa a comparação como sempre
        # falsa - embora funcione em runtime.
        if resposta.status_code == HTTP_403_FORBIDDEN:
            raise CompetenciaIndisponivelError(
                f"competência {competencia} não está disponível na fonte "
                "(403: a base foi descontinuada a partir de 202405)"
            )

        resposta.raise_for_status()
        return resposta.content
