"""Métricas de erro, com valores conferidos à mão.

O MASE é a métrica que responde à pergunta do trabalho: menor que 1 é melhor
que o baseline, maior que 1 é pior.
"""

import math

import pytest

from tcc_jobs.ml.evaluation import mae, mape, mase, rmse


def test_mae_calculado_a_mao() -> None:
    # erros: |1-2|=1, |5-3|=2, |0-3|=3 -> media 2
    assert mae([1.0, 5.0, 0.0], [2.0, 3.0, 3.0]) == 2.0


def test_rmse_calculado_a_mao() -> None:
    # erros ao quadrado: 1, 4, 9 -> media 14/3 -> raiz
    assert rmse([1.0, 5.0, 0.0], [2.0, 3.0, 3.0]) == pytest.approx(math.sqrt(14 / 3))


def test_rmse_pesa_o_erro_grande_mais_que_o_mae() -> None:
    observado = [10.0, 10.0, 10.0, 10.0]
    uniforme = [12.0, 12.0, 12.0, 12.0]  # erro 2 em todos
    concentrado = [10.0, 10.0, 10.0, 18.0]  # erro 8 num só

    assert mae(observado, uniforme) == mae(observado, concentrado) == 2.0
    assert rmse(observado, concentrado) > rmse(observado, uniforme)


def test_mape_calculado_a_mao() -> None:
    # |1-2|/1=1.0, |5-4|/5=0.2 -> media 0.6 -> 60%
    assert mape([1.0, 5.0], [2.0, 4.0]) == pytest.approx(60.0)


def test_mape_ignora_observado_zero_e_avisa_no_retorno() -> None:
    """Decisão explícita: observado zero acontece no dado real - competências
    sem licitação para um par órgão/modalidade. Dividir devolveria infinito e
    contaminaria a média; o ponto é ignorado e a quantidade ignorada é
    devolvida junto, para o descarte nunca ser silencioso."""
    valor, ignorados = mape([0.0, 5.0], [3.0, 4.0], com_ignorados=True)

    assert valor == pytest.approx(20.0)
    assert ignorados == 1


def test_mape_todo_zerado_devolve_nan() -> None:
    """Sem nenhum ponto válido não existe percentual - NaN, não zero: zero
    significaria previsão perfeita."""
    assert math.isnan(mape([0.0, 0.0], [1.0, 2.0]))


def test_mase_menor_que_um_significa_melhor_que_o_baseline() -> None:
    observado = [10.0, 20.0]
    modelo = [11.0, 21.0]  # MAE 1
    baseline = [14.0, 24.0]  # MAE 4

    assert mase(observado, modelo, baseline) == pytest.approx(0.25)


def test_mase_igual_a_um_significa_empate() -> None:
    observado = [10.0, 20.0]

    assert mase(observado, [12.0, 22.0], [8.0, 18.0]) == pytest.approx(1.0)


def test_mase_com_baseline_perfeito_e_nan() -> None:
    """Baseline com erro zero tornaria a razão infinita. NaN sinaliza que a
    comparação não se aplica - e o caso existe: séries constantes."""
    assert math.isnan(mase([10.0], [11.0], [10.0]))


def test_tamanhos_diferentes_sao_recusados() -> None:
    with pytest.raises(ValueError):
        mae([1.0], [1.0, 2.0])


def test_series_vazias_sao_recusadas() -> None:
    with pytest.raises(ValueError):
        mae([], [])
