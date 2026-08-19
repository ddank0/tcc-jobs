"""Envelope do AutoARIMA: testa protocolo, não acurácia.

"O modelo é bom" é resultado experimental, não asserção de teste. O que se
trava aqui: determinismo, forma da saída e robustez às séries degeneradas que
existem no dado real.
"""

import math

import pytest

from tcc_jobs.ml.forecast import Previsao, prever

# Série sintética com sazonalidade clara: nível 100, pico no fim do ciclo.
SERIE = [100.0 + (i % 12) * 10.0 + (i // 12) * 5.0 for i in range(48)]


def test_determinismo() -> None:
    """Mesma entrada e mesma seed, mesmo resultado - duas execuções."""
    a = prever(SERIE, h=6)
    b = prever(SERIE, h=6)

    assert a.pontual == b.pontual
    assert a.inferior == b.inferior
    assert a.superior == b.superior


def test_devolve_o_horizonte_pedido() -> None:
    p = prever(SERIE, h=12)

    assert len(p.pontual) == len(p.inferior) == len(p.superior) == 12


def test_intervalo_contem_a_previsao_pontual() -> None:
    p = prever(SERIE, h=6)

    for baixo, ponto, alto in zip(p.inferior, p.pontual, p.superior):
        assert baixo <= ponto <= alto


def test_serie_constante_nao_estoura() -> None:
    """Variância zero quebra estimadores, e séries assim existem na base."""
    p = prever([7.0] * 36, h=6)

    assert len(p.pontual) == 6
    assert all(math.isfinite(v) for v in p.pontual)
    assert all(abs(v - 7.0) < 1.0 for v in p.pontual)


def test_serie_com_zeros_nao_estoura() -> None:
    serie = [0.0, 0.0, 3.0] * 12

    p = prever(serie, h=6)

    assert all(math.isfinite(v) for v in p.pontual)


def test_serie_curta_demais_e_recusada() -> None:
    """Menos de dois ciclos não estima componente sazonal."""
    with pytest.raises(ValueError, match="ciclos"):
        prever([1.0] * 23, h=6)


def test_horizonte_invalido_e_recusado() -> None:
    with pytest.raises(ValueError):
        prever(SERIE, h=0)


def test_previsao_e_imutavel() -> None:
    """O resultado atravessa camadas; mutável viraria canal lateral."""
    p = prever(SERIE, h=3)

    assert isinstance(p, Previsao)
    with pytest.raises(AttributeError):
        p.pontual = []  # type: ignore[misc]
