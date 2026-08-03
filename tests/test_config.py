from pathlib import Path

from tcc_jobs.core.config import Settings


def test_settings_le_variaveis_de_ambiente(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@host:5432/db")
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql+psycopg://u:p@host:5432/db_test")
    monkeypatch.setenv("DATA_DIR", "/tmp/dados")

    s = Settings()

    assert s.database_url == "postgresql+psycopg://u:p@host:5432/db"
    assert s.test_database_url == "postgresql+psycopg://u:p@host:5432/db_test"
    assert s.data_dir == Path("/tmp/dados")


def test_data_dir_tem_padrao(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@host:5432/db")
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql+psycopg://u:p@host:5432/db_test")
    monkeypatch.delenv("DATA_DIR", raising=False)

    assert Settings().data_dir == Path("data")
