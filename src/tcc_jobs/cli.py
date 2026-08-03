import re

import typer

app = typer.Typer(help="Jobs de dados e modelos do TCC de licitações.")

PADRAO_COMPETENCIA = re.compile(r"^\d{4}(0[1-9]|1[0-2])$")


def validar_competencia(valor: str) -> str:
    """Valida competência no formato AAAAMM."""
    if not PADRAO_COMPETENCIA.match(valor):
        raise ValueError(f"competência inválida: {valor!r}. Use o formato AAAAMM, ex: 202401")
    return valor


def _validar_intervalo(de: str, ate: str) -> tuple[str, str]:
    try:
        validar_competencia(de)
        validar_competencia(ate)
    except ValueError as erro:
        raise typer.BadParameter(str(erro)) from erro
    if de > ate:
        raise typer.BadParameter(f"intervalo invertido: {de} é posterior a {ate}")
    return de, ate


@app.command()
def ingest(
    de: str = typer.Option(..., help="Competência inicial, AAAAMM"),
    ate: str = typer.Option(..., help="Competência final, AAAAMM"),
) -> None:
    """Baixa os ZIPs e grava Parquet limpo em silver."""
    de, ate = _validar_intervalo(de, ate)
    typer.echo(f"ingest {de}..{ate} - ainda não implementado")


@app.command()
def load(
    de: str = typer.Option(..., help="Competência inicial, AAAAMM"),
    ate: str = typer.Option(..., help="Competência final, AAAAMM"),
) -> None:
    """Carrega silver no PostgreSQL via COPY."""
    de, ate = _validar_intervalo(de, ate)
    typer.echo(f"load {de}..{ate} - ainda não implementado")


@app.command()
def aggregate() -> None:
    """Monta serie_mensal e a matriz de atributos."""
    typer.echo("aggregate - ainda não implementado")


@app.command()
def train(
    serie: str = typer.Option("orgao", help="Agrupamento: orgao, modalidade ou global"),
) -> None:
    """Treina os modelos de previsão e grava previsao."""
    typer.echo(f"train --serie {serie} - ainda não implementado")


@app.command()
def score() -> None:
    """Calcula scores de atipicidade e grava score_anomalia."""
    typer.echo("score - ainda não implementado")


if __name__ == "__main__":
    app()
