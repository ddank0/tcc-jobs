from collections.abc import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from tcc_jobs.core.config import settings
from tcc_jobs.db.base import Base
from tcc_jobs.db.session import criar_engine, criar_sessionmaker


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
