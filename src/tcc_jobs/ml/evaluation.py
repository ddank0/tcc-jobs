"""Backtesting e métricas de erro. Núcleo funcional.

Aqui mora o teste mais importante do projeto: a garantia de que nenhuma
janela de treino contém competência posterior à prevista. Um vazamento é
silencioso e melhora todas as métricas - por isso a geração de janelas é
pura e testada por mutação.
"""

from collections.abc import Iterator


def janelas(n_pontos: int, h: int, minimo_treino: int) -> Iterator[tuple[slice, slice]]:
    """Janelas expansivas de backtesting, sem sobreposição no teste.

    Gera pares (treino, teste) como slices de índice - a função não recebe
    dados de propósito: operar só sobre tamanhos é o que torna o não-vazamento
    verificável por inspeção dos índices, sem montar série nenhuma.

    As origens são ancoradas pelo FIM da série, andando para trás de h em h:
    o período mais recente é o que interessa avaliar, e ancorar pelo começo o
    deixaria de fora sempre que (n - minimo_treino) não fosse múltiplo de h.

    O treino é expansivo (começa sempre no ponto 0): janela deslizante
    descartaria história sem justificativa, e a comparação com o baseline
    exige que os dois vejam o mesmo passado.
    """
    if h < 1:
        raise ValueError(f"horizonte deve ser positivo, veio {h}")
    if minimo_treino < 1:
        raise ValueError(f"mínimo de treino deve ser positivo, veio {minimo_treino}")

    origens: list[int] = []
    origem = n_pontos - h
    while origem >= minimo_treino:
        origens.append(origem)
        origem -= h

    for inicio_teste in sorted(origens):
        yield slice(0, inicio_teste), slice(inicio_teste, inicio_teste + h)
