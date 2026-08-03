from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from tcc_jobs.db.base import Base


class Orgao(Base):
    """Órgão, conforme o código SIAFI.

    A hierarquia é auto-relacionamento: guardar o nome do superior aqui era
    dependência transitiva, porque ele depende de codigo_orgao_superior e não
    da chave primária.

    A FK é diferida porque a carga insere órgãos em lote, sem garantir que o
    superior apareça antes do subordinado - a verificação acontece no commit.
    """

    __tablename__ = "orgao"

    codigo_orgao: Mapped[str] = mapped_column(String(10), primary_key=True)
    nome: Mapped[str] = mapped_column(String(255))
    codigo_orgao_superior: Mapped[str | None] = mapped_column(
        ForeignKey("orgao.codigo_orgao", deferrable=True, initially="DEFERRED"),
        index=True,
    )


class UnidadeGestora(Base):
    """Unidade gestora responsável pela licitação.

    Recebe uf e municipio, que antes ficavam em licitacao: as dependências
    codigo_ug -> uf e codigo_ug -> municipio são funcionais perfeitas no dado
    real (0 violações em 772 unidades), então a localização pertence aqui.
    """

    __tablename__ = "unidade_gestora"

    codigo_ug: Mapped[str] = mapped_column(String(10), primary_key=True)
    nome: Mapped[str] = mapped_column(String(255))
    uf: Mapped[str | None] = mapped_column(String(2), index=True)
    municipio: Mapped[str | None] = mapped_column(String(100))
    codigo_orgao: Mapped[str] = mapped_column(ForeignKey("orgao.codigo_orgao"), index=True)


class Modalidade(Base):
    """Modalidade de compra.

    Tabela própria porque codigo_modalidade -> modalidade é dependência
    funcional perfeita: seis modalidades para milhares de licitações. Como
    dimensão, atende ao RF05 sem DISTINCT sobre milhões de linhas.
    """

    __tablename__ = "modalidade"

    codigo: Mapped[int] = mapped_column(Integer, primary_key=True)
    nome: Mapped[str] = mapped_column(String(100))


class Fornecedor(Base):
    """Participante de licitação, identificado pelo CNPJ."""

    __tablename__ = "fornecedor"

    cnpj: Mapped[str] = mapped_column(String(14), primary_key=True)
    nome: Mapped[str] = mapped_column(String(255))
