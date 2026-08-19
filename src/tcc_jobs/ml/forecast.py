"""Modelos de previsão. Núcleo funcional: recebem dados, devolvem dados.

Não importa db/ nem portal/ - a casca que lê serie_mensal e grava previsao
fica em runner.py. E não importa etl/: as camadas se comunicam por tabelas.
"""

from dataclasses import dataclass
from typing import cast

import pandas as pd
import polars as pl
from statsforecast import StatsForecast
from statsforecast.models import AutoARIMA

# Nível do intervalo de previsão, em percentual.
NIVEL_INTERVALO = 95


@dataclass(frozen=True)
class Previsao:
    """Previsão pontual e intervalo. Imutável: atravessa camadas."""

    pontual: list[float]
    inferior: list[float]
    superior: list[float]


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


def prever(serie: list[float], h: int, m: int = 12) -> Previsao:
    """AutoARIMA sazonal com intervalo de previsão.

    Envelope fino sobre o statsforecast, e é a fronteira que atende ao RNF08:
    trocar de algoritmo muda este módulo, nunca api/ ou etl/.

    Determinístico por construção - o AutoARIMA do statsforecast não usa
    aleatoriedade na seleção de ordem - e isso é travado por teste, não
    presumido: se uma versão futura introduzir sorteio, o teste acusa.
    """
    if h < 1:
        raise ValueError(f"horizonte deve ser positivo, veio {h}")
    if len(serie) < 2 * m:
        raise ValueError(
            f"série com {len(serie)} pontos não tem dois ciclos de {m} - "
            "sem isso o componente sazonal não é estimável"
        )

    dados = pl.DataFrame(
        {
            "unique_id": ["serie"] * len(serie),
            "ds": list(range(1, len(serie) + 1)),
            "y": serie,
        }
    ).to_pandas()

    modelo = StatsForecast(models=[AutoARIMA(season_length=m)], freq=1, n_jobs=1)
    modelo.fit(dados)
    # O predict devolve o mesmo tipo da entrada; a entrada aqui é pandas, e o
    # cast registra isso - o tipo declarado do statsforecast é um protocolo
    # que não expõe indexação.
    resultado = cast(pd.DataFrame, modelo.predict(h=h, level=[NIVEL_INTERVALO]))

    pontual = [float(v) for v in resultado["AutoARIMA"]]
    inferior = [float(v) for v in resultado[f"AutoARIMA-lo-{NIVEL_INTERVALO}"]]
    superior = [float(v) for v in resultado[f"AutoARIMA-hi-{NIVEL_INTERVALO}"]]

    return Previsao(pontual=pontual, inferior=inferior, superior=superior)
