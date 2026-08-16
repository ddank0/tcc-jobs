from decimal import Decimal

import polars as pl
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tcc_jobs.db.copiador import copiar_para_tabela


def _orgaos(n: int = 2) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "codigo_orgao": [f"{22000 + i}" for i in range(n)],
            "nome": [f"Órgão {i}" for i in range(n)],
            "codigo_orgao_superior": [None] * n,
        },
        schema={
            "codigo_orgao": pl.String,
            "nome": pl.String,
            "codigo_orgao_superior": pl.String,
        },
    )


def test_copia_linhas_para_a_tabela(sessao: Session, engine: Engine) -> None:
    df = _orgaos(2)

    with engine.begin() as conn:
        inseridas = copiar_para_tabela(conn, "orgao", df, list(df.columns))

    assert inseridas == 2
    assert sessao.execute(text("SELECT count(*) FROM orgao")).scalar() == 2


def test_preserva_acentuacao(sessao: Session, engine: Engine) -> None:
    df = pl.DataFrame(
        {
            "codigo_orgao": ["26000"],
            "nome": ["Ministério da Educação"],
            "codigo_orgao_superior": [None],
        },
        schema={
            "codigo_orgao": pl.String,
            "nome": pl.String,
            "codigo_orgao_superior": pl.String,
        },
    )

    with engine.begin() as conn:
        copiar_para_tabela(conn, "orgao", df, list(df.columns))

    assert sessao.execute(text("SELECT nome FROM orgao")).scalar() == "Ministério da Educação"


def test_preserva_precisao_decimal(sessao: Session, engine: Engine) -> None:
    """Decimal não pode passar por float: 4500000.1234 perderia precisão."""
    df = pl.DataFrame(
        {
            "competencia": ["202401"],
            "codigo_orgao": ["22000"],
            "codigo_modalidade": [5],
            "quantidade_licitacoes": [120],
            "valor_total": [Decimal("4500000.1234")],
            "valor_mediano": [Decimal("32000.5678")],
        },
        schema={
            "competencia": pl.String,
            "codigo_orgao": pl.String,
            "codigo_modalidade": pl.Int32,
            "quantidade_licitacoes": pl.Int32,
            "valor_total": pl.Decimal(18, 4),
            "valor_mediano": pl.Decimal(18, 4),
        },
    )

    with engine.begin() as conn:
        copiar_para_tabela(conn, "serie_mensal", df, list(df.columns))

    valor = sessao.execute(text("SELECT valor_total FROM serie_mensal")).scalar()
    assert valor == Decimal("4500000.1234")


def test_dataframe_vazio_nao_falha(sessao: Session, engine: Engine) -> None:
    df = _orgaos(0)

    with engine.begin() as conn:
        assert copiar_para_tabela(conn, "orgao", df, list(df.columns)) == 0


def test_nulos_chegam_como_null(sessao: Session, engine: Engine) -> None:
    with engine.begin() as conn:
        copiar_para_tabela(conn, "orgao", _orgaos(1), list(_orgaos(1).columns))

    resultado = sessao.execute(
        text("SELECT codigo_orgao_superior FROM orgao WHERE codigo_orgao = '22000'")
    ).scalar()
    assert resultado is None


def test_copia_volume_significativo(sessao: Session, engine: Engine) -> None:
    """Exercita o caminho real: são 21,8 milhões de linhas em produção."""
    df = _orgaos(20_000)

    with engine.begin() as conn:
        inseridas = copiar_para_tabela(conn, "orgao", df, list(df.columns))

    assert inseridas == 20_000
    assert sessao.execute(text("SELECT count(*) FROM orgao")).scalar() == 20_000
