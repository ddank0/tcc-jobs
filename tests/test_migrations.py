import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text

from tcc_jobs.core.config import settings

TABELAS_ESPERADAS = {
    "orgao",
    "unidade_gestora",
    "fornecedor",
    "licitacao",
    "item_licitacao",
    "participante_licitacao",
    "ingestao_log",
    "serie_mensal",
    "execucao_modelo",
    "previsao",
    "score_anomalia",
}


def _config() -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", settings.test_database_url)
    return cfg


@pytest.fixture
def banco_limpo(engine: Engine) -> Engine:
    """Zera o schema, inclusive alembic_version.

    A fixture `sessao` usa Base.metadata.drop_all, que não conhece a tabela
    alembic_version. Sem esta limpeza, o Alembic acharia a migration aplicada
    enquanto as tabelas não existem, e o downgrade quebraria.
    """
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    return engine


def test_upgrade_cria_todas_as_tabelas(banco_limpo: Engine) -> None:
    command.upgrade(_config(), "head")

    tabelas = set(inspect(banco_limpo).get_table_names())
    assert TABELAS_ESPERADAS <= tabelas


def test_chave_natural_existe_apos_upgrade(banco_limpo: Engine) -> None:
    command.upgrade(_config(), "head")

    constraints = inspect(banco_limpo).get_unique_constraints("licitacao")
    nomes = {c["name"] for c in constraints}
    assert "uq_licitacao_chave_natural" in nomes


def test_indices_criticos_existem(banco_limpo: Engine) -> None:
    """Sem estes índices, a carga de 21,8 milhões de linhas fica inviável."""
    command.upgrade(_config(), "head")

    insp = inspect(banco_limpo)
    colunas_indexadas = {
        col for idx in insp.get_indexes("participante_licitacao") for col in idx["column_names"]
    }
    assert {"licitacao_id", "cnpj_participante"} <= colunas_indexadas


def test_downgrade_remove_tudo(banco_limpo: Engine) -> None:
    cfg = _config()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    tabelas = set(inspect(banco_limpo).get_table_names())
    assert not (TABELAS_ESPERADAS & tabelas)
