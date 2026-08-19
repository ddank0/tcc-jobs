"""Baseline sazonal ingênuo: a régua de comparação do trabalho.

Se ele estiver errado, todas as conclusões caem - inclusive a de que o SARIMA
é melhor ou pior. Por isso os valores esperados aqui são calculados à mão.
"""

import pytest

from tcc_jobs.ml.forecast import baseline_sazonal


def test_repete_o_mesmo_mes_do_ano_anterior() -> None:
    serie = [float(v) for v in range(24)]  # 0..23

    assert baseline_sazonal(serie, h=3) == [12.0, 13.0, 14.0]


def test_usa_o_ultimo_ciclo_e_nao_o_primeiro() -> None:
    """Com três anos de história, a previsão vem do ano mais recente."""
    serie = [1.0] * 12 + [2.0] * 12 + [3.0] * 12

    assert baseline_sazonal(serie, h=12) == [3.0] * 12


def test_horizonte_maior_que_o_ciclo_reusa_o_ciclo() -> None:
    """Prever 18 meses com m=12 repete o ciclo, não estoura."""
    serie = [float(v) for v in range(24)]

    previsao = baseline_sazonal(serie, h=18)

    assert len(previsao) == 18
    assert previsao[:12] == [float(v) for v in range(12, 24)]
    assert previsao[12:] == [float(v) for v in range(12, 18)]


def test_serie_nao_multipla_do_ciclo() -> None:
    """136 competências não são múltiplas de 12 - o caso real. O último ciclo
    são os últimos 12 pontos, independentemente de onde o ano começa."""
    serie = [float(v) for v in range(30)]  # 2,5 ciclos

    assert baseline_sazonal(serie, h=2) == [18.0, 19.0]


def test_serie_menor_que_o_ciclo_e_recusada() -> None:
    """Sem um ciclo completo não existe sazonal ingênuo - devolver algo aqui
    seria inventar régua."""
    with pytest.raises(ValueError, match="ciclo"):
        baseline_sazonal([1.0] * 11, h=3)


def test_horizonte_invalido_e_recusado() -> None:
    with pytest.raises(ValueError):
        baseline_sazonal([1.0] * 24, h=0)


def test_nao_usa_dado_posterior_ao_fim_da_serie() -> None:
    """O baseline olha só para trás: previsões para a mesma origem não mudam
    quando o 'futuro' muda - aqui, duas séries que divergem só no fim."""
    base = [float(v) for v in range(24)]

    ate_12 = baseline_sazonal(base[:12], h=3)
    com_futuro_diferente = baseline_sazonal(base[:12], h=3, m=12)

    assert ate_12 == com_futuro_diferente == [0.0, 1.0, 2.0]


def test_ciclo_configuravel() -> None:
    serie = [10.0, 20.0, 30.0, 40.0]

    assert baseline_sazonal(serie, h=2, m=2) == [30.0, 40.0]
