"""Casca do score: monta a matriz, pontua e grava score_anomalia."""

from pathlib import Path

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tcc_jobs.core.competencia import Competencia
from tcc_jobs.db.carga import carregar
from tcc_jobs.etl.armazenamento import Armazenamento
from tcc_jobs.etl.pipeline import ingerir
from tcc_jobs.ml.runner import pontuar_universo
from tests.conftest import CriarCliente

C = Competencia.de_str("202401")


def _base_carregada(tmp_path: Path, engine: Engine, criar_cliente: CriarCliente) -> Armazenamento:
    arm = Armazenamento(tmp_path)
    ingerir([C], criar_cliente(), arm)
    carregar([C], arm, engine)
    return arm


def test_grava_score_ranking_e_features(
    sessao: Session, engine: Engine, tmp_path: Path, criar_cliente: CriarCliente
) -> None:
    arm = _base_carregada(tmp_path, engine, criar_cliente)

    resultado = pontuar_universo(engine, arm.silver, seed=42)

    assert resultado.pontuadas == 30  # a fixture tem 30 licitações
    linhas = sessao.execute(
        text("SELECT count(*), count(DISTINCT posicao_ranking) FROM score_anomalia")
    ).one()
    assert linhas[0] == 30
    assert linhas[1] == 30, "ranking denso: uma posição por licitação"


def test_ranking_ordena_pelo_score(
    sessao: Session, engine: Engine, tmp_path: Path, criar_cliente: CriarCliente
) -> None:
    arm = _base_carregada(tmp_path, engine, criar_cliente)
    pontuar_universo(engine, arm.silver, seed=42)

    fora_de_ordem = sessao.execute(
        text("""
        SELECT count(*) FROM score_anomalia a
        JOIN score_anomalia b ON b.posicao_ranking = a.posicao_ranking + 1
        WHERE b.score > a.score
        """)
    ).scalar()
    assert fora_de_ordem == 0


def test_features_json_carrega_as_contribuicoes(
    sessao: Session, engine: Engine, tmp_path: Path, criar_cliente: CriarCliente
) -> None:
    arm = _base_carregada(tmp_path, engine, criar_cliente)
    pontuar_universo(engine, arm.silver, seed=42)

    primeiro = sessao.execute(
        text("SELECT features_json FROM score_anomalia WHERE posicao_ranking = 1")
    ).scalar()
    assert primeiro is not None
    assert "contribuicoes" in primeiro
    assert "valores" in primeiro


def test_repontuar_substitui(
    sessao: Session, engine: Engine, tmp_path: Path, criar_cliente: CriarCliente
) -> None:
    arm = _base_carregada(tmp_path, engine, criar_cliente)

    pontuar_universo(engine, arm.silver, seed=42)
    pontuar_universo(engine, arm.silver, seed=42)

    assert sessao.execute(text("SELECT count(*) FROM score_anomalia")).scalar() == 30
    assert (
        sessao.execute(
            text("SELECT count(*) FROM execucao_modelo WHERE tipo = 'anomaly:licitacao'")
        ).scalar()
        == 1
    )


def test_execucao_registra_seed_e_parametros(
    sessao: Session, engine: Engine, tmp_path: Path, criar_cliente: CriarCliente
) -> None:
    arm = _base_carregada(tmp_path, engine, criar_cliente)
    pontuar_universo(engine, arm.silver, seed=7)

    parametros = sessao.execute(
        text("SELECT parametros_json FROM execucao_modelo WHERE tipo = 'anomaly:licitacao'")
    ).scalar()
    assert parametros is not None
    assert parametros["seed"] == 7
