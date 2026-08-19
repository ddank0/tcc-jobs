"""Backtesting e métricas de erro. Núcleo funcional.

Aqui mora o teste mais importante do projeto: a garantia de que nenhuma
janela de treino contém competência posterior à prevista. Um vazamento é
silencioso e melhora todas as métricas - por isso a geração de janelas é
pura e testada por mutação.
"""

import math
import random
from collections.abc import Iterator
from typing import Literal, overload

import polars as pl


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


def _validar(observado: list[float], previsto: list[float]) -> None:
    if len(observado) != len(previsto):
        raise ValueError(
            f"tamanhos diferentes: {len(observado)} observados, {len(previsto)} previstos"
        )
    if not observado:
        raise ValueError("séries vazias não têm erro definido")


def mae(observado: list[float], previsto: list[float]) -> float:
    """Erro absoluto médio, na unidade da série."""
    _validar(observado, previsto)
    return sum(abs(o - p) for o, p in zip(observado, previsto, strict=True)) / len(observado)


def rmse(observado: list[float], previsto: list[float]) -> float:
    """Raiz do erro quadrático médio: pesa erro grande mais que o MAE."""
    _validar(observado, previsto)
    return math.sqrt(
        sum((o - p) ** 2 for o, p in zip(observado, previsto, strict=True)) / len(observado)
    )


@overload
def mape(observado: list[float], previsto: list[float]) -> float: ...
@overload
def mape(
    observado: list[float], previsto: list[float], *, com_ignorados: Literal[True]
) -> tuple[float, int]: ...


def mape(
    observado: list[float], previsto: list[float], *, com_ignorados: bool = False
) -> float | tuple[float, int]:
    """Erro percentual absoluto médio.

    Observado zero acontece no dado real - competências sem licitação para um
    par órgão/modalidade. Dividir devolveria infinito e contaminaria a média,
    então o ponto é ignorado; com `com_ignorados=True` a quantidade descartada
    vem junto, para o descarte nunca ser silencioso.

    Sem nenhum ponto válido o resultado é NaN, não zero: zero significaria
    previsão perfeita.
    """
    _validar(observado, previsto)

    validos = [(o, p) for o, p in zip(observado, previsto, strict=True) if o != 0.0]
    ignorados = len(observado) - len(validos)

    if not validos:
        valor = math.nan
    else:
        valor = 100.0 * sum(abs((o - p) / o) for o, p in validos) / len(validos)

    return (valor, ignorados) if com_ignorados else valor


def mase(observado: list[float], previsto: list[float], baseline: list[float]) -> float:
    """Erro do modelo relativo ao do baseline, sobre a mesma janela.

    É a métrica que responde à pergunta do trabalho: menor que 1, o modelo é
    melhor que o baseline sazonal ingênuo; maior que 1, pior.

    Baseline com erro zero devolve NaN - a razão não se aplica, e o caso
    existe em séries constantes.
    """
    erro_baseline = mae(observado, baseline)
    if erro_baseline == 0.0:
        return math.nan
    return mae(observado, previsto) / erro_baseline


def perturbar(matriz: pl.DataFrame, quantos: int, seed: int) -> tuple[pl.DataFrame, list[int]]:
    """Perturba `quantos` linhas de forma controlada e devolve os índices.

    Frente 1 da avaliação sem rótulos: planta-se atipicidade conhecida e
    mede-se a recuperação.

    As perturbações são MULTIPLICATIVAS sobre o valor da própria linha, não
    valores absolutos. A primeira versão plantava alvos absolutos - taxa de
    vitória 1,0, HHI 0,7-1,0 - e o experimento revelou que isso é TÍPICO
    nesta base: a mediana real de taxa_vitoria_vencedor é 1,0, consequência
    dos 70,3% de licitações com participante único. Plantar o típico e cobrar
    recuperação mede o gerador, não o detector. Atipicidade só existe em
    relação ao contexto - a mesma lição das features vale para a avaliação.

    Determinístico por seed.
    """
    if quantos > matriz.height:
        raise ValueError(f"pedidas {quantos} perturbações numa matriz de {matriz.height}")

    sorteio = random.Random(seed)
    indices = sorted(sorteio.sample(range(matriz.height), quantos))

    linhas = matriz.to_dicts()
    for i in indices:
        tipo = sorteio.choice(("valor", "competicao", "sazonal"))
        if tipo == "valor":
            fator = sorteio.uniform(10.0, 100.0)
            linhas[i]["razao_valor_grupo"] = max(linhas[i]["razao_valor_grupo"], 1.0) * fator
            linhas[i]["razao_item_max"] = max(linhas[i]["razao_item_max"], 1.0) * fator
        elif tipo == "competicao":
            # competição desabando EM RELAÇÃO ao próprio contexto: só é
            # perturbação onde havia competição
            linhas[i]["razao_participantes_modalidade"] = linhas[i][
                "razao_participantes_modalidade"
            ] * sorteio.uniform(0.01, 0.05)
            linhas[i]["razao_valor_grupo"] = max(
                linhas[i]["razao_valor_grupo"], 1.0
            ) * sorteio.uniform(5.0, 20.0)
        else:
            linhas[i]["desvio_sazonal_orgao"] = max(
                linhas[i]["desvio_sazonal_orgao"], 1.0
            ) * sorteio.uniform(8.0, 20.0)
            linhas[i]["razao_valor_grupo"] = max(
                linhas[i]["razao_valor_grupo"], 1.0
            ) * sorteio.uniform(5.0, 20.0)

    return pl.DataFrame(linhas, schema=matriz.schema), indices
