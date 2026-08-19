from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Index,
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

    Não guarda nome de modalidade nem localização: ambos eram dependências
    transitivas e foram para as dimensões correspondentes. Ver
    [[Licitações - Decisões de Modelagem]].
    """

    __tablename__ = "licitacao"
    __table_args__ = (
        UniqueConstraint(
            "numero_licitacao",
            "codigo_ug",
            "codigo_modalidade",
            name="uq_licitacao_chave_natural",
        ),
        # GIN trigram, e não B-tree: a API busca com ILIKE '%termo%', e o
        # curinga à esquerda impede o uso da árvore. Medido: 1.137 ms de
        # Parallel Seq Scan contra 10 ms com este índice.
        Index(
            "ix_licitacao_objeto_trgm",
            "objeto",
            postgresql_using="gin",
            postgresql_ops={"objeto": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    numero_licitacao: Mapped[str] = mapped_column(String(20))
    codigo_ug: Mapped[str] = mapped_column(ForeignKey("unidade_gestora.codigo_ug"))
    codigo_modalidade: Mapped[int] = mapped_column(ForeignKey("modalidade.codigo"), index=True)

    numero_processo: Mapped[str | None] = mapped_column(String(50))
    objeto: Mapped[str | None] = mapped_column(Text)
    situacao: Mapped[str | None] = mapped_column(String(100))

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
    # Sem índice: medido em 809 MB e zero usos depois de todos os endpoints
    # da API exercitados, e a coluna não sustenta chave estrangeira - não há
    # FK de participante para item, porque 12.424 participantes por competência
    # apontam para item inexistente. As features de competitividade agregam a
    # partir do silver, não do banco. Recriar custa ~20 s se algum plano
    # futuro precisar.
    codigo_item_compra: Mapped[str] = mapped_column(String(30))
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
