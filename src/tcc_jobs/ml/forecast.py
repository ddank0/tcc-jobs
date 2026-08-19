"""Modelos de previsão. Núcleo funcional: recebem dados, devolvem dados.

Não importa db/ nem portal/ - a casca que lê serie_mensal e grava previsao
fica em runner.py. E não importa etl/: as camadas se comunicam por tabelas.
"""


def baseline_sazonal(serie: list[float], h: int, m: int = 12) -> list[float]:
    """Previsão ingênua sazonal: o valor do mesmo ponto do ciclo anterior.

    É a régua contra a qual todo modelo é medido - um SARIMA que não a supera
    não justifica a própria complexidade. A implementação é deliberadamente
    trivial: qualquer sofisticação aqui contaminaria a comparação.

    Para horizonte maior que o ciclo, o último ciclo se repete: o baseline não
    conhece tendência, e fingir que conhece o tornaria outro modelo.
    """
    if h < 1:
        raise ValueError(f"horizonte deve ser positivo, veio {h}")
    if m < 1:
        raise ValueError(f"ciclo deve ser positivo, veio {m}")
    if len(serie) < m:
        raise ValueError(
            f"série com {len(serie)} pontos não completa um ciclo de {m} - "
            "sem um ciclo inteiro não existe previsão sazonal ingênua"
        )

    ultimo_ciclo = serie[-m:]
    return [ultimo_ciclo[i % m] for i in range(h)]
