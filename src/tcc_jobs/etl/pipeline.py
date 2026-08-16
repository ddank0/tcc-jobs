"""Orquestração do job ingest.

Casca imperativa: recebe cliente e armazenamento por injeção, chama o núcleo
puro dos parsers e escreve o resultado em disco.
"""

import logging
from dataclasses import dataclass, field

import polars as pl

from tcc_jobs.core.competencia import Competencia
from tcc_jobs.etl.armazenamento import Armazenamento
from tcc_jobs.etl.parsers import (
    extrair_do_zip,
    parse_item,
    parse_licitacao,
    parse_participante,
)
from tcc_jobs.portal.client import ClientePortal, CompetenciaIndisponivelError

logger = logging.getLogger(__name__)

# Nome do CSV no ZIP -> nome da tabela em silver.
# EmpenhosRelacionados fica de fora: não entra no modelo de dados.
TABELAS = ("licitacao", "item", "participante")


@dataclass
class ResultadoIngestao:
    competencia: Competencia
    linhas_por_tabela: dict[str, int] = field(default_factory=dict)
    veio_do_cache: bool = False
    erro: str | None = None


def _converter(arquivos: dict[str, bytes], competencia: Competencia) -> dict[str, pl.DataFrame]:
    """Aplica o parser correspondente a cada CSV. Núcleo puro."""
    return {
        "licitacao": parse_licitacao(arquivos.get("Licitação", b""), competencia),
        "item": parse_item(arquivos.get("ItemLicitação", b"")),
        "participante": parse_participante(arquivos.get("ParticipantesLicitação", b"")),
    }


def ingerir(
    competencias: list[Competencia],
    cliente: ClientePortal,
    armazenamento: Armazenamento,
    forcar_download: bool = False,
) -> list[ResultadoIngestao]:
    """Baixa, converte e grava em silver, uma competência por vez.

    Competência indisponível não interrompe as demais: de 202405 em diante a
    fonte devolve 403, e isso é o fim da janela documentada, não falha do job.
    """
    return [_ingerir_uma(c, cliente, armazenamento, forcar_download) for c in competencias]


def _ingerir_uma(
    competencia: Competencia,
    cliente: ClientePortal,
    armazenamento: Armazenamento,
    forcar_download: bool,
) -> ResultadoIngestao:
    resultado = ResultadoIngestao(competencia=competencia)

    try:
        conteudo = None if forcar_download else armazenamento.ler_bronze(competencia)
        if conteudo is None:
            conteudo = cliente.baixar(competencia)
            armazenamento.gravar_bronze(competencia, conteudo)
        else:
            resultado.veio_do_cache = True

        quadros = _converter(extrair_do_zip(conteudo), competencia)

        for tabela in TABELAS:
            df = quadros[tabela]
            armazenamento.gravar_silver(competencia, tabela, df)
            resultado.linhas_por_tabela[tabela] = df.height

        logger.info("ingest %s: %s", competencia, resultado.linhas_por_tabela)

    except CompetenciaIndisponivelError as erro:
        resultado.erro = str(erro)
        logger.warning("ingest %s: %s", competencia, erro)
    except Exception as erro:  # noqa: BLE001 - uma competência ruim não derruba o lote
        resultado.erro = f"{type(erro).__name__}: {erro}"
        logger.exception("ingest %s falhou", competencia)

    return resultado
