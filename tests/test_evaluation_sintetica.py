"""Gerador de perturbações sintéticas para a avaliação sem rótulos.

Perturba registros reais de forma controlada e verificável - a frente 1 da
avaliação mede se o detector recupera exatamente esses registros.
"""

import polars as pl

from tcc_jobs.ml.evaluation import perturbar

_MATRIZ = pl.DataFrame(
    {
        "razao_valor_grupo": [1.0] * 50,
        "razao_participantes_modalidade": [1.0] * 50,
        "taxa_vitoria_vencedor": [0.3] * 50,
        "hhi_orgao": [0.05] * 50,
        "razao_item_max": [1.0] * 50,
        "desvio_sazonal_orgao": [1.0] * 50,
        "sem_vencedor": [0.0] * 50,
        "contem_item_implausivel": [0.0] * 50,
    }
)


def test_perturba_a_quantidade_pedida_e_devolve_os_indices() -> None:
    perturbada, indices = perturbar(_MATRIZ, quantos=10, seed=42)

    assert perturbada.height == 50
    assert len(indices) == len(set(indices)) == 10
    assert all(0 <= i < 50 for i in indices)


def test_perturbacao_muda_de_fato_as_linhas_marcadas() -> None:
    perturbada, indices = perturbar(_MATRIZ, quantos=10, seed=42)

    for i in indices:
        original = _MATRIZ.row(i, named=True)
        nova = perturbada.row(i, named=True)
        assert original != nova, f"linha {i} marcada como perturbada mas idêntica"


def test_linhas_nao_marcadas_ficam_intactas() -> None:
    perturbada, indices = perturbar(_MATRIZ, quantos=10, seed=42)
    marcadas = set(indices)

    for i in range(50):
        if i not in marcadas:
            assert _MATRIZ.row(i) == perturbada.row(i)


def test_mesma_seed_mesma_perturbacao() -> None:
    a, ia = perturbar(_MATRIZ, quantos=10, seed=42)
    b, ib = perturbar(_MATRIZ, quantos=10, seed=42)

    assert ia == ib
    assert a.equals(b)


def test_perturbacao_e_relativa_ao_contexto() -> None:
    """Multiplicativa sobre a própria linha, nunca alvo absoluto: a primeira
    versão plantava taxa de vitória 1,0 - que É a mediana real desta base
    (70,3% de participante único) - e cobrava do detector recuperar o típico."""
    perturbada, indices = perturbar(_MATRIZ, quantos=20, seed=42)

    for i in indices:
        linha = perturbada.row(i, named=True)
        original = _MATRIZ.row(i, named=True)
        # alguma razão foi multiplicada para além do original
        assert (
            linha["razao_valor_grupo"] > original["razao_valor_grupo"]
            or linha["razao_participantes_modalidade"] < original["razao_participantes_modalidade"]
            or linha["desvio_sazonal_orgao"] > original["desvio_sazonal_orgao"]
        )
        assert linha["razao_participantes_modalidade"] >= 0.0


def test_quantos_maior_que_a_matriz_e_recusado() -> None:
    import pytest

    with pytest.raises(ValueError):
        perturbar(_MATRIZ, quantos=51, seed=42)
