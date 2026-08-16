from datetime import datetime

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from tcc_jobs.core.competencia import Competencia
from tcc_jobs.db.log_ingestao import registrar, ultima_ingestao

C = Competencia.de_str("202401")


def test_registra_e_recupera(sessao: Session, engine: Engine) -> None:
    registrar(
        engine,
        competencia=C,
        arquivo="202401_Licitação.csv",
        lidas=2537,
        inseridas=2500,
        atualizadas=37,
        rejeitadas=0,
        iniciado_em=datetime(2026, 8, 16, 10, 0),
        finalizado_em=datetime(2026, 8, 16, 10, 2),
        status="sucesso",
    )

    ultima = ultima_ingestao(engine)
    assert ultima is not None
    assert ultima["competencia"] == "202401"
    assert ultima["linhas_lidas"] == 2537
    assert ultima["status"] == "sucesso"


def test_sem_registro_devolve_none(sessao: Session, engine: Engine) -> None:
    assert ultima_ingestao(engine) is None


def test_registra_falha_com_mensagem(sessao: Session, engine: Engine) -> None:
    registrar(
        engine,
        competencia=Competencia.de_str("202405"),
        arquivo="-",
        lidas=0,
        inseridas=0,
        atualizadas=0,
        rejeitadas=0,
        iniciado_em=datetime(2026, 8, 16, 10, 0),
        finalizado_em=datetime(2026, 8, 16, 10, 0),
        status="erro",
        mensagem_erro="403: competência indisponível",
    )

    ultima = ultima_ingestao(engine)
    assert ultima is not None
    assert ultima["status"] == "erro"
    assert ultima["mensagem_erro"] is not None
    assert "403" in ultima["mensagem_erro"]


def test_ultima_e_a_mais_recente(sessao: Session, engine: Engine) -> None:
    for comp, hora in (("202401", 10), ("202402", 11)):
        registrar(
            engine,
            competencia=Competencia.de_str(comp),
            arquivo="x",
            lidas=1,
            inseridas=1,
            atualizadas=0,
            rejeitadas=0,
            iniciado_em=datetime(2026, 8, 16, hora, 0),
            finalizado_em=datetime(2026, 8, 16, hora, 5),
            status="sucesso",
        )

    ultima = ultima_ingestao(engine)
    assert ultima is not None
    assert ultima["competencia"] == "202402"


def test_carga_registra_automaticamente(
    sessao: Session, engine: Engine, tmp_path: object, criar_cliente: object
) -> None:
    """O job load precisa registrar sem que ninguém chame registrar à mão -
    senão o RF10 depende de disciplina."""
    from pathlib import Path

    from tcc_jobs.db.carga import carregar
    from tcc_jobs.etl.armazenamento import Armazenamento
    from tcc_jobs.etl.pipeline import ingerir

    assert isinstance(tmp_path, Path)
    arm = Armazenamento(tmp_path)
    ingerir([C], criar_cliente(), arm)  # type: ignore[operator]

    carregar([C], arm, engine)

    ultima = ultima_ingestao(engine)
    assert ultima is not None
    assert ultima["competencia"] == "202401"
    assert ultima["status"] == "sucesso"
