"""Casca do job aggregate: lê do banco, agrega, grava serie_mensal.

O núcleo puro tem teste desde a T10; esta casca não tinha nenhum, e é ela que
liga a série temporal ao banco. O JOIN com `unidade_gestora` é a única
atribuição de órgão da série que alimenta o SARIMA - errado ali, todas as
séries se deslocam sem que nada acuse.
"""

from decimal import Decimal
from pathlib import Path

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tcc_jobs.core.competencia import Competencia
from tcc_jobs.db.agregacao_carga import agregar
from tcc_jobs.db.carga import carregar
from tests.conftest import CriarCliente

C = Competencia.de_str("202401")


def _carregado(tmp_path: Path, engine: Engine, criar_cliente: CriarCliente) -> None:
    from tcc_jobs.etl.armazenamento import Armazenamento
    from tcc_jobs.etl.pipeline import ingerir

    arm = Armazenamento(tmp_path)
    ingerir([C], criar_cliente(), arm)
    carregar([C], arm, engine)


def test_agrega_a_partir_do_banco(
    sessao: Session, engine: Engine, tmp_path: Path, criar_cliente: CriarCliente
) -> None:
    _carregado(tmp_path, engine, criar_cliente)

    total = agregar(engine)

    assert total > 0
    assert sessao.execute(text("SELECT count(*) FROM serie_mensal")).scalar() == total


def test_soma_das_series_bate_com_licitacao(
    sessao: Session, engine: Engine, tmp_path: Path, criar_cliente: CriarCliente
) -> None:
    """Se o JOIN com unidade_gestora perdesse linhas, a série ficaria menor que
    a fonte - e a previsão treinaria sobre um recorte silencioso."""
    _carregado(tmp_path, engine, criar_cliente)

    agregar(engine)

    licitacoes = sessao.execute(text("SELECT count(*) FROM licitacao")).scalar()
    agregadas = sessao.execute(text("SELECT sum(quantidade_licitacoes) FROM serie_mensal")).scalar()

    assert agregadas == licitacoes


def test_valor_total_bate_com_a_soma_da_fonte(
    sessao: Session, engine: Engine, tmp_path: Path, criar_cliente: CriarCliente
) -> None:
    _carregado(tmp_path, engine, criar_cliente)

    agregar(engine)

    da_fonte = sessao.execute(text("SELECT coalesce(sum(valor), 0) FROM licitacao")).scalar()
    da_serie = sessao.execute(
        text("SELECT coalesce(sum(valor_total), 0) FROM serie_mensal")
    ).scalar()

    assert da_serie == da_fonte


def test_orgao_vem_da_unidade_gestora(
    sessao: Session, engine: Engine, tmp_path: Path, criar_cliente: CriarCliente
) -> None:
    """A licitação referencia a UG, e é a UG que pertence ao órgão.

    Um JOIN por outro caminho produziria códigos que não existem em `orgao`.
    """
    _carregado(tmp_path, engine, criar_cliente)

    agregar(engine)

    desconhecidos = sessao.execute(
        text("""
        SELECT count(*) FROM serie_mensal s
        LEFT JOIN orgao o ON o.codigo_orgao = s.codigo_orgao
        WHERE o.codigo_orgao IS NULL
        """)
    ).scalar()

    assert desconhecidos == 0


def test_reagregar_nao_duplica(
    sessao: Session, engine: Engine, tmp_path: Path, criar_cliente: CriarCliente
) -> None:
    """O TRUNCATE antes do COPY é o que torna o recálculo repetível.

    Sem ele, cada execução somaria uma cópia inteira da série - e o job existe
    justamente para ser barato de repetir durante a experimentação.
    """
    _carregado(tmp_path, engine, criar_cliente)

    primeira = agregar(engine)
    segunda = agregar(engine)

    assert primeira == segunda
    assert sessao.execute(text("SELECT count(*) FROM serie_mensal")).scalar() == primeira


def test_banco_vazio_nao_estoura(sessao: Session, engine: Engine) -> None:
    """Rodar aggregate antes de load é engano comum, não deve virar exceção."""
    assert agregar(engine) == 0


def test_mediana_por_grupo_confere(
    sessao: Session, engine: Engine, tmp_path: Path, criar_cliente: CriarCliente
) -> None:
    """Recalcula a mediana em SQL e compara com a que o Polars gravou."""
    _carregado(tmp_path, engine, criar_cliente)

    agregar(engine)

    divergentes = sessao.execute(
        text("""
        SELECT count(*) FROM serie_mensal s
        JOIN (
            SELECT l.competencia, u.codigo_orgao, l.codigo_modalidade,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY l.valor) AS mediana
            FROM licitacao l
            JOIN unidade_gestora u ON u.codigo_ug = l.codigo_ug
            GROUP BY 1, 2, 3
        ) esperado
          ON esperado.competencia = s.competencia
         AND esperado.codigo_orgao = s.codigo_orgao
         AND esperado.codigo_modalidade = s.codigo_modalidade
        WHERE abs(s.valor_mediano - esperado.mediana) > 0.0001
        """)
    ).scalar()

    assert divergentes == 0


def test_serie_nao_tem_nulos(
    sessao: Session, engine: Engine, tmp_path: Path, criar_cliente: CriarCliente
) -> None:
    """Nulo em valor_total ou valor_mediano quebraria o treino do SARIMA."""
    _carregado(tmp_path, engine, criar_cliente)

    agregar(engine)

    nulos = sessao.execute(
        text("""
        SELECT count(*) FROM serie_mensal
        WHERE valor_total IS NULL OR valor_mediano IS NULL
           OR quantidade_licitacoes IS NULL OR codigo_orgao IS NULL
        """)
    ).scalar()

    assert nulos == 0


def test_decimal_nao_perde_precisao(
    sessao: Session, engine: Engine, tmp_path: Path, criar_cliente: CriarCliente
) -> None:
    """O cast para Decimal(18,4) na mediana não pode arredondar o total."""
    _carregado(tmp_path, engine, criar_cliente)

    agregar(engine)

    total = sessao.execute(text("SELECT sum(valor_total) FROM serie_mensal")).scalar()

    assert isinstance(total, Decimal)
    assert total == total.quantize(Decimal("0.0001"))
