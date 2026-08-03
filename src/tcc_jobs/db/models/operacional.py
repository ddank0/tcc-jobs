from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from tcc_jobs.db.base import Base


class IngestaoLog(Base):
    """Registro de cada arquivo processado. Atende ao RF10."""

    __tablename__ = "ingestao_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    competencia: Mapped[str] = mapped_column(String(6), index=True)
    arquivo: Mapped[str] = mapped_column(String(255))

    linhas_lidas: Mapped[int] = mapped_column(Integer, default=0)
    linhas_inseridas: Mapped[int] = mapped_column(Integer, default=0)
    linhas_atualizadas: Mapped[int] = mapped_column(Integer, default=0)
    linhas_rejeitadas: Mapped[int] = mapped_column(Integer, default=0)

    iniciado_em: Mapped[datetime] = mapped_column(DateTime)
    finalizado_em: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20))
    mensagem_erro: Mapped[str | None] = mapped_column(Text)
