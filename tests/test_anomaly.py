"""Envelope do IsolationForest: protocolo, não acurácia.

Aqui a seed é real - o IsolationForest sorteia subamostras por árvore - e o
determinismo precisa dela, ao contrário do AutoARIMA.
"""

import math

import polars as pl
import pytest

from tcc_jobs.ml.anomaly import Scores, pontuar

# 200 linhas típicas e 3 fora da nuvem
_TIPICAS = {
    "razao_valor_grupo": [1.0 + (i % 10) * 0.05 for i in range(200)],
    "razao_participantes_modalidade": [1.0] * 200,
    "hhi_orgao": [0.02] * 200,
}
_ATIPICAS = {
    "razao_valor_grupo": [80.0, 1.0, 95.0],
    "razao_participantes_modalidade": [1.0, 0.05, 0.05],
    "hhi_orgao": [0.02, 0.9, 0.85],
}


def _matriz() -> pl.DataFrame:
    return pl.DataFrame({k: _TIPICAS[k] + _ATIPICAS[k] for k in _TIPICAS})


def test_determinismo_com_a_mesma_seed() -> None:
    a = pontuar(_matriz(), seed=42)
    b = pontuar(_matriz(), seed=42)

    assert a.valores == b.valores


def test_seeds_diferentes_produzem_scores_diferentes() -> None:
    """Prova que a seed controla algo de verdade - se fosse inerte, o
    determinismo do teste anterior seria vácuo."""
    a = pontuar(_matriz(), seed=42)
    b = pontuar(_matriz(), seed=7)

    assert a.valores != b.valores


def test_maior_score_significa_mais_atipico() -> None:
    """A orientação é decidida aqui e documentada: o sklearn devolve invertido
    (menor = mais anômalo), e servir isso cru confundiria todo consumidor."""
    s = pontuar(_matriz(), seed=42)

    tipicos = s.valores[:200]
    atipicos = s.valores[200:]
    assert min(atipicos) > sorted(tipicos)[len(tipicos) // 2], (
        "os plantados fora da nuvem precisam pontuar acima da mediana típica"
    )


def test_tamanho_da_saida() -> None:
    s = pontuar(_matriz(), seed=42)

    assert len(s.valores) == 203


def test_nulo_e_recusado_com_mensagem_clara() -> None:
    com_nulo = _matriz().with_columns(
        pl.when(pl.arange(0, 203) == 5).then(None).otherwise(pl.col("hhi_orgao")).alias("hhi_orgao")
    )

    with pytest.raises(ValueError, match="nulo"):
        pontuar(com_nulo, seed=42)


def test_uma_linha_nao_estoura() -> None:
    s = pontuar(_matriz().head(1), seed=42)

    assert len(s.valores) == 1
    assert math.isfinite(s.valores[0])


def test_matriz_vazia_e_recusada() -> None:
    with pytest.raises(ValueError):
        pontuar(_matriz().head(0), seed=42)


def test_coluna_constante_nao_estoura() -> None:
    """IQR zero na normalização robusta dividiria por zero; colunas constantes
    existem em recortes reais."""
    constante = _matriz().with_columns(pl.lit(0.5).alias("hhi_orgao"))

    s = pontuar(constante, seed=42)

    assert all(math.isfinite(v) for v in s.valores)


def test_scores_imutaveis() -> None:
    s = pontuar(_matriz(), seed=42)

    assert isinstance(s, Scores)
    with pytest.raises(AttributeError):
        s.valores = []  # type: ignore[misc]
