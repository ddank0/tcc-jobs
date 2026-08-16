from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from tcc_jobs.core.competencia import Competencia
from tcc_jobs.core.config import settings
from tcc_jobs.db.base import Base
from tcc_jobs.db.session import criar_engine, criar_sessionmaker
from tcc_jobs.portal.client import CompetenciaIndisponivelError

FIXTURE_ZIP = Path(__file__).parent / "fixtures" / "202401_amostra.zip"


@pytest.fixture(scope="session")
def engine() -> Engine:
    return criar_engine(settings.test_database_url)


@pytest.fixture
def sessao(engine: Engine) -> Iterator[Session]:
    """Recria o esquema a cada teste, para isolamento total.

    Importa Base depois dos modelos estarem registrados - por isso
    db/models/__init__.py precisa reexportar todos, senão create_all
    cria apenas parte das tabelas.
    """
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with criar_sessionmaker(engine)() as s:
        yield s


class ClientePortalFalso:
    """Dublê do ClientePortal: conta chamadas e não usa rede.

    Fica no conftest porque o teste de ingestão e o de carga usam o mesmo -
    importar entre arquivos de teste depende do sys.path e é frágil.
    """

    def __init__(self, conteudo: bytes, indisponiveis: set[str] | None = None) -> None:
        self._conteudo = conteudo
        self._indisponiveis = indisponiveis or set()
        self.chamadas: list[str] = []

    def baixar(self, competencia: Competencia) -> bytes:
        self.chamadas.append(str(competencia))
        if str(competencia) in self._indisponiveis:
            raise CompetenciaIndisponivelError(f"{competencia} indisponível")
        return self._conteudo


@pytest.fixture
def zip_amostra() -> bytes:
    return FIXTURE_ZIP.read_bytes()


CriarCliente = Callable[..., ClientePortalFalso]


@pytest.fixture
def criar_cliente(zip_amostra: bytes) -> CriarCliente:
    """Fábrica do dublê, exposta como fixture.

    Classe no conftest não é importável dos testes - `tests` não é pacote, e
    torná-lo um só para isso acopla a suíte ao sys.path. Fixture é o mecanismo
    que o pytest oferece para compartilhar entre arquivos.
    """

    def _criar(
        conteudo: bytes | None = None,
        indisponiveis: set[str] | None = None,
    ) -> ClientePortalFalso:
        return ClientePortalFalso(zip_amostra if conteudo is None else conteudo, indisponiveis)

    return _criar
