from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from tcc_jobs.db.base import Base


class Orgao(Base):
    """Órgão superior ou subordinado, conforme o código SIAFI."""

    __tablename__ = "orgao"

    codigo_orgao: Mapped[str] = mapped_column(String(10), primary_key=True)
    nome: Mapped[str] = mapped_column(String(255))
    codigo_orgao_superior: Mapped[str | None] = mapped_column(String(10))
    nome_orgao_superior: Mapped[str | None] = mapped_column(String(255))


class UnidadeGestora(Base):
    """Unidade gestora responsável pela licitação."""

    __tablename__ = "unidade_gestora"

    codigo_ug: Mapped[str] = mapped_column(String(10), primary_key=True)
    nome: Mapped[str] = mapped_column(String(255))
    codigo_orgao: Mapped[str] = mapped_column(ForeignKey("orgao.codigo_orgao"), index=True)


class Fornecedor(Base):
    """Participante de licitação, identificado pelo CNPJ."""

    __tablename__ = "fornecedor"

    cnpj: Mapped[str] = mapped_column(String(14), primary_key=True)
    nome: Mapped[str] = mapped_column(String(255))
