"""Acesso ao disco nas camadas bronze e silver.

Casca imperativa: toca em disco. A raiz é injetada, então os testes usam
tmp_path e nada escapa para o volume real.
"""

from pathlib import Path

import polars as pl

from tcc_jobs.core.competencia import Competencia


class Armazenamento:
    """Camadas bronze e silver do medalhão.

    Bronze guarda o ZIP como veio da fonte e nunca é transformado: descobrir
    um erro de conversão semanas depois exige reprocessar a partir dele, sem
    rebaixar 136 arquivos.

    Silver guarda Parquet tipado, particionado por tabela e competência.
    """

    def __init__(self, raiz: Path) -> None:
        self._raiz = raiz

    @property
    def bronze(self) -> Path:
        return self._raiz / "bronze"

    @property
    def silver(self) -> Path:
        return self._raiz / "silver"

    def _caminho_bronze(self, competencia: Competencia) -> Path:
        return self.bronze / f"{competencia}.zip"

    def gravar_bronze(self, competencia: Competencia, conteudo: bytes) -> Path:
        caminho = self._caminho_bronze(competencia)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(conteudo)
        return caminho

    def ler_bronze(self, competencia: Competencia) -> bytes | None:
        caminho = self._caminho_bronze(competencia)
        return caminho.read_bytes() if caminho.exists() else None

    def caminho_silver(self, competencia: Competencia, tabela: str) -> Path:
        return self.silver / tabela / f"{competencia}.parquet"

    def gravar_silver(self, competencia: Competencia, tabela: str, df: pl.DataFrame) -> Path:
        caminho = self.caminho_silver(competencia, tabela)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(caminho, compression="zstd")
        return caminho
