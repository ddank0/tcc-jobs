"""Detector de atipicidade. Núcleo funcional.

O vocabulário é deliberado em todo o módulo: score e atipicidade, nunca
termos que sugiram irregularidade - restrição de produto, não de estilo.
"""

from dataclasses import dataclass

import numpy as np
import polars as pl
from sklearn.ensemble import IsolationForest

# Árvores do ensemble. O custo medido no universo real (1,74M x 8) com 100
# árvores é de ~7s - não há motivo para economizar aqui.
N_ARVORES = 100


@dataclass(frozen=True)
class Scores:
    """Scores de atipicidade, na ordem das linhas da matriz. Imutável."""

    valores: list[float]


def _normalizar_robusto(matriz: pl.DataFrame) -> np.ndarray:
    """Mediana e IQR, não média e desvio: as caudas do dado real são pesadas
    (razões de valor chegam a 10^8), e média/desvio seriam dominados por elas.

    Coluna constante tem IQR zero; o divisor vira 1 para a coluna sair neutra
    em vez de dividir por zero.
    """
    x = matriz.to_numpy().astype(np.float64)
    mediana = np.median(x, axis=0)
    q75, q25 = np.percentile(x, 75, axis=0), np.percentile(x, 25, axis=0)
    iqr = q75 - q25
    iqr[iqr == 0.0] = 1.0
    return (x - mediana) / iqr


def pontuar(matriz: pl.DataFrame, seed: int = 42) -> Scores:
    """IsolationForest sobre a matriz de features, com orientação corrigida.

    O sklearn devolve score invertido - menor significa mais anômalo - e
    servir isso cru confundiria todo consumidor. Aqui, MAIOR score significa
    MAIS atípico, e essa orientação é travada por teste.

    A seed é real: o IsolationForest sorteia subamostras por árvore. Mesma
    matriz e mesma seed produzem os mesmos scores.
    """
    if matriz.height == 0:
        raise ValueError("matriz vazia não tem o que pontuar")

    nulos = {c: matriz[c].null_count() for c in matriz.columns if matriz[c].null_count()}
    if nulos:
        raise ValueError(
            f"a matriz tem valores nulos em {sorted(nulos)} - o tratamento de nulo "
            "pertence à montagem das features, não ao detector"
        )

    x = _normalizar_robusto(matriz)

    modelo = IsolationForest(n_estimators=N_ARVORES, random_state=seed, n_jobs=-1)
    modelo.fit(x)
    invertido = modelo.score_samples(x)

    return Scores(valores=[float(-v) for v in invertido])


def contribuicoes(matriz: pl.DataFrame) -> list[list[tuple[str, float]]]:
    """Desvio robusto de cada atributo, por linha, ordenado do maior ao menor.

    Não é SHAP - fora de escopo declarado. É |z-score robusto|: quanto cada
    atributo está longe do típico da população, em unidades de IQR. Responde
    "o que torna este registro atípico" de forma contestável: quem discorda
    olha o valor da feature, que a API devolve junto.

    Booleanos entram na mesma régua: um valor raro (IQR zero substituído por
    1) desvia da mediana e contribui; o comum contribui zero.
    """
    if matriz.height == 0:
        return []

    nomes = matriz.columns
    z = np.abs(_normalizar_robusto(matriz))

    return [
        sorted(
            ((nome, float(z[i, j])) for j, nome in enumerate(nomes)),
            key=lambda par: par[1],
            reverse=True,
        )
        for i in range(z.shape[0])
    ]
