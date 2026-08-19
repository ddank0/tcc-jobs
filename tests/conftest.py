from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session

from tcc_jobs.core.competencia import Competencia
from tcc_jobs.core.config import settings
from tcc_jobs.db import models
from tcc_jobs.db.base import Base
from tcc_jobs.db.session import criar_engine, criar_sessionmaker
from tcc_jobs.portal.client import CompetenciaIndisponivelError

# O import de models não é usado diretamente, mas é o que popula
# Base.metadata. Sem ele, a fixture `sessao` chama drop_all sobre um metadata
# vazio e não limpa nada - o que só aparece em teste que usa o banco sem
# importar modelo por conta própria, deixando dado vazar entre testes.
_ = models

FIXTURE_ZIP = Path(__file__).parent / "fixtures" / "202401_amostra.zip"


@pytest.fixture(scope="session")
def engine() -> Engine:
    return criar_engine(settings.test_database_url)


@pytest.fixture
def sessao(engine: Engine) -> Iterator[Session]:
    """Deixa o banco limpo antes de cada teste.

    TRUNCATE em vez de drop_all mais create_all: são 12 tabelas e dezenas de
    testes que usam banco, e o DDL passa a dominar o tempo da suíte - medido,
    a diferença é de 167s para 8s.

    Recria o esquema quando ele não existe, porque os testes de migration
    derrubam o schema inteiro.
    """
    esperadas = set(Base.metadata.tables)
    existentes = set(inspect(engine).get_table_names())

    if not esperadas <= existentes:
        with engine.begin() as conn:
            # O índice trigram de licitacao.objeto exige a extensão; sem ela o
            # create_all falha num banco recém-criado - caso do CI.
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        Base.metadata.create_all(engine)
    else:
        with engine.begin() as conn:
            nomes = ", ".join(f'"{t}"' for t in esperadas)
            conn.execute(text(f"TRUNCATE {nomes} RESTART IDENTITY CASCADE"))

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
