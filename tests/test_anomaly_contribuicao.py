"""Contribuição dos atributos: o que torna o score contestável.

Não é SHAP - fora de escopo declarado. É o desvio robusto de cada atributo em
relação à população: responde "o que está longe do típico neste registro", e
o método fica documentado na API.
"""

import polars as pl

from tcc_jobs.ml.anomaly import contribuicoes


def _matriz() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "razao_valor_grupo": [1.0, 1.1, 0.9, 1.0, 50.0],
            "hhi_orgao": [0.02, 0.03, 0.02, 0.02, 0.02],
            "sem_vencedor": [False, False, False, False, True],
        }
    )


def test_uma_lista_por_linha_com_todas_as_features() -> None:
    c = contribuicoes(_matriz())

    assert len(c) == 5
    assert {nome for nome, _ in c[0]} == {"razao_valor_grupo", "hhi_orgao", "sem_vencedor"}


def test_atributo_desviado_domina_a_contribuicao() -> None:
    c = contribuicoes(_matriz())
    atipica = c[4]  # valor 50x e sem vencedor

    assert atipica[0][0] in ("razao_valor_grupo", "sem_vencedor")
    assert atipica[0][1] > atipica[-1][1]


def test_registro_tipico_contribui_perto_de_zero() -> None:
    c = contribuicoes(_matriz())
    tipica = c[0]

    assert all(v < 1.0 for _, v in tipica)


def test_ordenada_do_maior_para_o_menor() -> None:
    for linha in contribuicoes(_matriz()):
        valores = [v for _, v in linha]
        assert valores == sorted(valores, reverse=True)


def test_contribuicao_e_nao_negativa() -> None:
    """É magnitude de desvio: direção fica visível no valor da feature, que a
    API devolve junto."""
    for linha in contribuicoes(_matriz()):
        assert all(v >= 0.0 for _, v in linha)


def test_booleano_conta_como_desvio_quando_raro() -> None:
    c = contribuicoes(_matriz())

    sem_venc = dict(c[4])["sem_vencedor"]
    com_venc = dict(c[0])["sem_vencedor"]
    assert sem_venc > com_venc


def test_nenhum_nome_usa_vocabulario_proibido() -> None:
    proibidos = ("suspeit", "irregular", "fraude", "ilicit", "ilegal")

    for nome, _ in contribuicoes(_matriz())[0]:
        assert not any(p in nome.lower() for p in proibidos)
