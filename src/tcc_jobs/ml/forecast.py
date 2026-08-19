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

from tcc_jobs.core.competencia import Competencia

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

    # Truncar em zero, nos três: o domínio é contagem e valor, e não existe
    # -1.312 licitações. O ARIMA é irrestrito e extrapola queda para baixo de
    # zero - na primeira rodada persistida, 512 das 3.492 previsões de
    # quantidade vieram negativas. Quando a previsão inteira é negativa o
    # intervalo degenera para [0, 0], que é a leitura honesta de
    # "essencialmente zero" - truncar só o pontual quebraria a invariante
    # inferior <= pontual <= superior.
    pontual = [max(0.0, float(v)) for v in resultado["AutoARIMA"]]
    inferior = [max(0.0, float(v)) for v in resultado[f"AutoARIMA-lo-{NIVEL_INTERVALO}"]]
    superior = [max(0.0, float(v)) for v in resultado[f"AutoARIMA-hi-{NIVEL_INTERVALO}"]]

    return Previsao(pontual=pontual, inferior=inferior, superior=superior)


@dataclass(frozen=True)
class SerieTemporal:
    """Uma série de treino: um par órgão/modalidade, ordenado no tempo."""

    codigo_orgao: str
    codigo_modalidade: int
    competencias: list[str]
    quantidades: list[float]
    valores: list[float]


@dataclass(frozen=True)
class Selecao:
    """Séries elegíveis mais a contagem do que ficou de fora.

    O descarte contado faz parte do resultado: 575 séries da base têm menos de
    24 meses e somam 0,4% do volume - descartá-las é defensável, escondê-las
    seria viés.
    """

    series: list[SerieTemporal]
    elegiveis: int
    descartadas: int


def selecionar_series(lf: pl.LazyFrame, minimo_treino: int, h: int) -> Selecao:
    """Separa as séries com história suficiente para treinar e avaliar.

    Elegível é a série com pelo menos `minimo_treino + h` pontos: menos que
    isso não produz nem uma janela de backtesting válida.

    Mês sem linha vira zero, não buraco: ausência em serie_mensal significa
    zero licitações naquele mês. Medido na base real: 84,9% das séries têm
    lacuna, somando 51.950 meses - sem o preenchimento, a posição na lista
    deixa de corresponder ao mês do calendário e a sazonalidade m=12
    desalinha. Cada série é preenchida do seu primeiro mês até a última
    competência do universo, para todas partirem do mesmo presente.
    """
    corte = minimo_treino + h

    materializado = lf.collect()
    if materializado.height == 0:
        return Selecao(series=[], elegiveis=0, descartadas=0)

    fim = Competencia.de_str(str(materializado["competencia"].max()))

    df = (
        materializado.lazy()
        .sort("competencia")
        .group_by(["codigo_orgao", "codigo_modalidade"], maintain_order=True)
        .agg(
            pl.col("competencia"),
            pl.col("quantidade_licitacoes").cast(pl.Float64).alias("quantidades"),
            pl.col("valor_total").cast(pl.Float64).alias("valores"),
        )
        .collect()
    )

    series: list[SerieTemporal] = []
    descartadas = 0
    for linha in df.iter_rows(named=True):
        calendario = [
            str(c) for c in Competencia.intervalo(Competencia.de_str(linha["competencia"][0]), fim)
        ]
        presentes = dict(
            zip(
                linha["competencia"],
                zip(linha["quantidades"], linha["valores"], strict=True),
                strict=True,
            )
        )
        cheia = [presentes.get(c, (0.0, 0.0)) for c in calendario]

        if len(calendario) < corte:
            descartadas += 1
            continue

        series.append(
            SerieTemporal(
                codigo_orgao=str(linha["codigo_orgao"]),
                codigo_modalidade=int(linha["codigo_modalidade"]),
                competencias=calendario,
                quantidades=[q for q, _ in cheia],
                valores=[v for _, v in cheia],
            )
        )

    return Selecao(
        series=series,
        elegiveis=len(series),
        descartadas=descartadas,
    )
