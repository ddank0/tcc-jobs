"""Backtesting sem vazamento temporal.

O teste mais importante do projeto. Um vazamento - janela de treino contendo
ponto posterior ao previsto - é silencioso, melhora todas as métricas e
invalida o trabalho inteiro. Nenhuma outra falha tem esse perfil.
"""

from tcc_jobs.ml.evaluation import janelas


def _indices(n: int, fatia: slice) -> list[int]:
    return list(range(n))[fatia]


def test_nenhuma_janela_de_treino_alcanca_o_futuro() -> None:
    """A asserção central: para toda janela, o treino termina antes do teste
    começar. Se isto passar por acidente, o trabalho fica sem fundamento."""
    for treino, teste in janelas(n_pontos=60, h=12, minimo_treino=24):
        assert max(_indices(60, treino)) < min(_indices(60, teste))


def test_treino_e_teste_sao_contiguos() -> None:
    """Buraco entre treino e teste avaliaria uma origem que não existe."""
    for treino, teste in janelas(n_pontos=60, h=12, minimo_treino=24):
        assert max(_indices(60, treino)) + 1 == min(_indices(60, teste))


def test_janelas_avancam_e_nao_se_sobrepoem_no_teste() -> None:
    """Teste sobreposto contaria o mesmo erro duas vezes."""
    testes = [_indices(60, t) for _, t in janelas(n_pontos=60, h=12, minimo_treino=24)]

    vistos: set[int] = set()
    for indices in testes:
        assert not (vistos & set(indices)), "ponto avaliado duas vezes"
        vistos.update(indices)


def test_respeita_o_minimo_de_treino() -> None:
    """Menos de dois ciclos não sustenta modelo sazonal."""
    for treino, _ in janelas(n_pontos=60, h=12, minimo_treino=24):
        assert len(_indices(60, treino)) >= 24


def test_o_teste_tem_o_tamanho_do_horizonte() -> None:
    for _, teste in janelas(n_pontos=60, h=12, minimo_treino=24):
        assert len(_indices(60, teste)) == 12


def test_serie_curta_demais_nao_gera_janela() -> None:
    """Zero janelas, e não uma janela inválida."""
    assert list(janelas(n_pontos=30, h=12, minimo_treino=24)) == []


def test_serie_no_limite_gera_exatamente_uma() -> None:
    resultado = list(janelas(n_pontos=36, h=12, minimo_treino=24))

    assert len(resultado) == 1
    treino, teste = resultado[0]
    assert _indices(36, treino) == list(range(24))
    assert _indices(36, teste) == list(range(24, 36))


def test_cobre_o_fim_da_serie() -> None:
    """A última janela alcança o último ponto - senão o período mais recente,
    que é o que interessa, nunca é avaliado."""
    ultima = list(janelas(n_pontos=61, h=12, minimo_treino=24))[-1]

    assert max(_indices(61, ultima[1])) == 60


def test_treino_cresce_e_comeca_sempre_no_zero() -> None:
    """Janela expansiva: o treino usa toda a história disponível até a origem.
    Janela deslizante descartaria dado sem justificativa aqui."""
    for treino, _ in janelas(n_pontos=60, h=12, minimo_treino=24):
        assert min(_indices(60, treino)) == 0


def test_136_pontos_o_caso_real() -> None:
    """A série real tem 136 competências. Ancorando pelo fim para cobrir o
    período mais recente, as origens são 28, 40, ..., 124 - nove janelas de
    passo 12, e a última alcança o ponto 135."""
    resultado = list(janelas(n_pontos=136, h=12, minimo_treino=24))

    assert len(resultado) == 9
    assert max(_indices(136, resultado[-1][1])) == 135
