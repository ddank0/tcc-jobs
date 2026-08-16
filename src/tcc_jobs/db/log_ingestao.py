"""Registro de execuções de ingestão. Atende ao RF10.

Aqui o ORM é adequado: são poucas linhas por execução, e a clareza vale mais
que o desempenho - ao contrário da carga em massa, que usa COPY.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Engine, select

from tcc_jobs.core.competencia import Competencia
from tcc_jobs.db.models import IngestaoLog
from tcc_jobs.db.session import criar_sessionmaker


def registrar(
    engine: Engine,
    *,
    competencia: Competencia,
    arquivo: str,
    lidas: int,
    inseridas: int,
    atualizadas: int,
    rejeitadas: int,
    iniciado_em: datetime,
    finalizado_em: datetime,
    status: str,
    mensagem_erro: str | None = None,
) -> None:
    """Grava uma linha em ingestao_log."""
    with criar_sessionmaker(engine)() as sessao:
        sessao.add(
            IngestaoLog(
                competencia=str(competencia),
                arquivo=arquivo,
                linhas_lidas=lidas,
                linhas_inseridas=inseridas,
                linhas_atualizadas=atualizadas,
                linhas_rejeitadas=rejeitadas,
                iniciado_em=iniciado_em,
                finalizado_em=finalizado_em,
                status=status,
                mensagem_erro=mensagem_erro,
            )
        )
        sessao.commit()


def ultima_ingestao(engine: Engine) -> dict[str, Any] | None:
    """Ingestão mais recente, para o endpoint de health da API.

    A API não executa job, mas precisa saber quando o último rodou.
    """
    with criar_sessionmaker(engine)() as sessao:
        log = sessao.scalars(
            select(IngestaoLog).order_by(IngestaoLog.finalizado_em.desc()).limit(1)
        ).first()

        if log is None:
            return None

        return {
            "competencia": log.competencia,
            "arquivo": log.arquivo,
            "linhas_lidas": log.linhas_lidas,
            "linhas_inseridas": log.linhas_inseridas,
            "linhas_atualizadas": log.linhas_atualizadas,
            "linhas_rejeitadas": log.linhas_rejeitadas,
            "status": log.status,
            "mensagem_erro": log.mensagem_erro,
            "finalizado_em": log.finalizado_em.isoformat() if log.finalizado_em else None,
        }
