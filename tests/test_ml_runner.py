"""Casca do treino: lê serie_mensal, treina e grava previsao e execucao_modelo."""

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tcc_jobs.ml.runner import treinar


def _semear_serie(sessao: Session, meses: int = 48) -> None:
    """Uma série sintética com sazonalidade, longa o bastante para treinar."""
    linhas = []
    for i in range(meses):
        ano, mes = 2013 + i // 12, i % 12 + 1
        linhas.append(f"('{ano}{mes:02d}', '26000', 5, {100 + (i % 12) * 10}, 1000.0000, 500.0000)")
    sessao.execute(
        text(
            "INSERT INTO serie_mensal (competencia, codigo_orgao, codigo_modalidade,"
            " quantidade_licitacoes, valor_total, valor_mediano) VALUES " + ", ".join(linhas)
        )
    )
    sessao.commit()


def test_treino_grava_execucao_e_previsoes(sessao: Session, engine: Engine) -> None:
    _semear_serie(sessao)

    resultado = treinar(engine, agrupamento="orgao", h=6)

    assert resultado.series_treinadas == 1
    execucoes = sessao.execute(text("SELECT count(*) FROM execucao_modelo")).scalar()
    previsoes = sessao.execute(text("SELECT count(*) FROM previsao")).scalar()
    assert execucoes == 1
    # 6 competências x 2 alvos (quantidade e valor)
    assert previsoes == 12


def test_previsoes_apontam_para_o_futuro(sessao: Session, engine: Engine) -> None:
    """A última competência semeada é 201612; a previsão começa em 201701."""
    _semear_serie(sessao)

    treinar(engine, agrupamento="orgao", h=3)

    alvos = (
        sessao.execute(text("SELECT DISTINCT competencia_alvo FROM previsao ORDER BY 1"))
        .scalars()
        .all()
    )
    assert list(alvos) == ["201701", "201702", "201703"]


def test_serie_chave_tem_o_formato_documentado(sessao: Session, engine: Engine) -> None:
    _semear_serie(sessao)

    treinar(engine, agrupamento="orgao", h=3)

    chaves = sessao.execute(text("SELECT DISTINCT serie_chave FROM previsao")).scalars().all()
    assert list(chaves) == ["orgao:26000"]


def test_intervalo_acompanha_a_previsao(sessao: Session, engine: Engine) -> None:
    _semear_serie(sessao)

    treinar(engine, agrupamento="orgao", h=3)

    fora = sessao.execute(
        text("""
        SELECT count(*) FROM previsao
        WHERE ic_inferior > valor_previsto OR ic_superior < valor_previsto
        """)
    ).scalar()
    assert fora == 0


def test_retreinar_substitui_e_nao_acumula(sessao: Session, engine: Engine) -> None:
    """Reprocessamento idempotente: a rodada anterior do mesmo agrupamento sai."""
    _semear_serie(sessao)

    treinar(engine, agrupamento="orgao", h=3)
    treinar(engine, agrupamento="orgao", h=3)

    execucoes = sessao.execute(
        text("SELECT count(*) FROM execucao_modelo WHERE tipo = 'forecast:orgao'")
    ).scalar()
    assert execucoes == 1
    previsoes = sessao.execute(text("SELECT count(*) FROM previsao")).scalar()
    assert previsoes == 6


def test_serie_curta_e_descartada_e_contada(sessao: Session, engine: Engine) -> None:
    _semear_serie(sessao, meses=20)

    resultado = treinar(engine, agrupamento="orgao", h=6)

    assert resultado.series_treinadas == 0
    assert resultado.series_descartadas == 1
    previsoes = sessao.execute(text("SELECT count(*) FROM previsao")).scalar()
    assert previsoes == 0


def test_banco_vazio_nao_estoura(sessao: Session, engine: Engine) -> None:
    resultado = treinar(engine, agrupamento="orgao", h=6)

    assert resultado.series_treinadas == 0


def test_agrupamento_invalido_e_recusado(engine: Engine) -> None:
    with pytest.raises(ValueError, match="agrupamento"):
        treinar(engine, agrupamento="cnpj", h=6)


def test_execucao_registra_parametros_e_janela(sessao: Session, engine: Engine) -> None:
    """Sem parâmetros persistidos não há como comparar configurações na defesa."""
    _semear_serie(sessao)

    treinar(engine, agrupamento="orgao", h=6)

    linha = sessao.execute(
        text(
            "SELECT algoritmo, parametros_json, janela_treino_inicio, janela_treino_fim"
            " FROM execucao_modelo"
        )
    ).one()
    assert linha[0] == "AutoARIMA"
    assert linha[2] == "201301"
    assert linha[3] == "201612"
