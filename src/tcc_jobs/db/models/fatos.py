from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from tcc_jobs.db.base import Base


class Licitacao(Base):
    """Licitação do Poder Executivo Federal.

    A chave natural (numero_licitacao, codigo_ug, codigo_modalidade) é o que
    relaciona os três CSVs de origem entre si e o que torna a ingestão
    idempotente: a mesma competência pode ser reprocessada sem duplicar.
    """

    __tablename__ = "licitacao"
    __table_args__ = (
        UniqueConstraint(
            "numero_licitacao",
            "codigo_ug",
            "codigo_modalidade",
            name="uq_licitacao_chave_natural",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    numero_licitacao: Mapped[str] = mapped_column(String(20))
    codigo_ug: Mapped[str] = mapped_column(ForeignKey("unidade_gestora.codigo_ug"))
    codigo_modalidade: Mapped[int] = mapped_column(Integer, index=True)

    modalidade: Mapped[str] = mapped_column(String(100))
    numero_processo: Mapped[str | None] = mapped_column(String(50))
    objeto: Mapped[str | None] = mapped_column(Text)
    situacao: Mapped[str | None] = mapped_column(String(100))
    uf: Mapped[str | None] = mapped_column(String(2))
    municipio: Mapped[str | None] = mapped_column(String(100))

    data_abertura: Mapped[date | None] = mapped_column(Date, index=True)
    data_resultado: Mapped[date | None] = mapped_column(Date)
    valor: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))

    competencia: Mapped[str] = mapped_column(String(6), index=True)


class ItemLicitacao(Base):
    """Item licitado, com quantidade, valor e vencedor."""

    __tablename__ = "item_licitacao"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    licitacao_id: Mapped[int] = mapped_column(
        ForeignKey("licitacao.id", ondelete="CASCADE"), index=True
    )
    codigo_item_compra: Mapped[str] = mapped_column(String(30), index=True)
    descricao: Mapped[str | None] = mapped_column(Text)
    quantidade: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    valor_item: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    cnpj_vencedor: Mapped[str | None] = mapped_column(ForeignKey("fornecedor.cnpj"))


class ParticipanteLicitacao(Base):
    """Concorrente de um item, com indicação de vitória.

    É a tabela que habilita os atributos de competitividade usados na
    detecção de anomalias: número de participantes, taxa de vitória por
    fornecedor e concentração de vencedores por órgão.
    """

    __tablename__ = "participante_licitacao"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    licitacao_id: Mapped[int] = mapped_column(
        ForeignKey("licitacao.id", ondelete="CASCADE"), index=True
    )
    codigo_item_compra: Mapped[str] = mapped_column(String(30))
    cnpj_participante: Mapped[str] = mapped_column(ForeignKey("fornecedor.cnpj"), index=True)
    flag_vencedor: Mapped[bool] = mapped_column(Boolean, default=False)
