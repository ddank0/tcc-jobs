from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from tcc_jobs.db.base import Base


class SerieMensal(Base):
    """Agregado mensal que alimenta a previsão e a análise histórica."""

    __tablename__ = "serie_mensal"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    competencia: Mapped[str] = mapped_column(String(6), index=True)
    codigo_orgao: Mapped[str | None] = mapped_column(String(10), index=True)
    codigo_modalidade: Mapped[int | None] = mapped_column(Integer)
    quantidade_licitacoes: Mapped[int] = mapped_column(Integer, default=0)
    valor_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    valor_mediano: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))


class RankingFornecedor(Base):
    """Itens vencidos por competência e fornecedor.

    Existe porque o ranking a partir de `item_licitacao` leva 7.866 ms na base
    cheia - 26x o orçamento de 500 ms -, e a API não executa cálculo caro.
    Populada pelo `aggregate` a partir do silver.
    """

    __tablename__ = "ranking_fornecedor"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    competencia: Mapped[str] = mapped_column(String(6), index=True)
    cnpj: Mapped[str] = mapped_column(String(20), index=True)
    itens_vencidos: Mapped[int] = mapped_column(Integer, default=0)
    licitacoes_distintas: Mapped[int] = mapped_column(Integer, default=0)
    # Numeric(38, 4) e não (18, 4): `valor_item * quantidade` chega a 9,6e20 no
    # dado real, e 1.232 itens passam do limite de 18 dígitos.
    valor_total: Mapped[Decimal | None] = mapped_column(Numeric(38, 4))


class RankingFornecedorTotal(Base):
    """Ranking global, colapsando as competências.

    Somar as 1,65 milhão de linhas de `ranking_fornecedor` em tempo de request
    custa 1.530 ms, e o ranking sem filtro de período é o que a tela de análise
    histórica abre por padrão. Aqui são 326 mil linhas.
    """

    __tablename__ = "ranking_fornecedor_total"

    cnpj: Mapped[str] = mapped_column(String(20), primary_key=True)
    itens_vencidos: Mapped[int] = mapped_column(Integer, default=0)
    licitacoes_distintas: Mapped[int] = mapped_column(Integer, default=0)
    valor_total: Mapped[Decimal | None] = mapped_column(Numeric(38, 4))


class ExecucaoModelo(Base):
    """Uma rodada de treino ou scoring, com parâmetros e métricas.

    Persistir isto é o que permite comparar configurações na defesa, em vez
    de apresentar um número isolado sem procedência.
    """

    __tablename__ = "execucao_modelo"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tipo: Mapped[str] = mapped_column(String(20), index=True)
    algoritmo: Mapped[str] = mapped_column(String(50))
    parametros_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metricas_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    janela_treino_inicio: Mapped[str | None] = mapped_column(String(6))
    janela_treino_fim: Mapped[str | None] = mapped_column(String(6))
    executado_em: Mapped[datetime] = mapped_column(DateTime)


class Previsao(Base):
    """Previsão por série e competência, com intervalo de confiança.

    O campo serie_chave usa o formato tipo:codigo - orgao:22000,
    modalidade:5, global - o que evita criar uma tabela de séries.
    """

    __tablename__ = "previsao"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    execucao_id: Mapped[int] = mapped_column(
        ForeignKey("execucao_modelo.id", ondelete="CASCADE"), index=True
    )
    serie_chave: Mapped[str] = mapped_column(String(50), index=True)
    competencia_alvo: Mapped[str] = mapped_column(String(6), index=True)
    alvo: Mapped[str] = mapped_column(String(20))
    valor_previsto: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    ic_inferior: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    ic_superior: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))


class ScoreAnomalia(Base):
    """Score de atipicidade por licitação.

    O vocabulário é deliberado: score e posição de ranking, nunca termos que
    sugiram irregularidade. O sistema aponta desvio estatístico em relação ao
    histórico, não fraude.
    """

    __tablename__ = "score_anomalia"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    execucao_id: Mapped[int] = mapped_column(
        ForeignKey("execucao_modelo.id", ondelete="CASCADE"), index=True
    )
    licitacao_id: Mapped[int] = mapped_column(
        ForeignKey("licitacao.id", ondelete="CASCADE"), index=True
    )
    score: Mapped[Decimal] = mapped_column(Numeric(12, 6), index=True)
    posicao_ranking: Mapped[int | None] = mapped_column(Integer)
    features_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
