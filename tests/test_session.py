from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tcc_jobs.core.config import settings
from tcc_jobs.db.session import criar_engine, criar_sessionmaker


def test_criar_engine_devolve_engine():
    engine = criar_engine(settings.test_database_url)
    assert isinstance(engine, Engine)


def test_conexao_com_banco_de_teste_funciona():
    engine = criar_engine(settings.test_database_url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1


def test_sessionmaker_produz_sessao_utilizavel():
    engine = criar_engine(settings.test_database_url)
    with criar_sessionmaker(engine)() as sessao:
        assert isinstance(sessao, Session)
        assert sessao.execute(text("SELECT 42")).scalar() == 42
