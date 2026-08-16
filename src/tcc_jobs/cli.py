import typer

from tcc_jobs.core.competencia import Competencia

app = typer.Typer(help="Jobs de dados e modelos do TCC de licitações.")


def _intervalo(de: str, ate: str) -> list[Competencia]:
    """Converte e valida o intervalo, traduzindo o erro para a CLI."""
    try:
        return Competencia.intervalo(Competencia.de_str(de), Competencia.de_str(ate))
    except ValueError as erro:
        raise typer.BadParameter(str(erro)) from erro


@app.command()
def ingest(
    de: str = typer.Option(..., help="Competência inicial, AAAAMM"),
    ate: str = typer.Option(..., help="Competência final, AAAAMM"),
) -> None:
    """Baixa os ZIPs e grava Parquet limpo em silver."""
    competencias = _intervalo(de, ate)
    typer.echo(f"ingest {competencias[0]}..{competencias[-1]} - ainda não implementado")


@app.command()
def load(
    de: str = typer.Option(..., help="Competência inicial, AAAAMM"),
    ate: str = typer.Option(..., help="Competência final, AAAAMM"),
) -> None:
    """Carrega silver no PostgreSQL via COPY."""
    competencias = _intervalo(de, ate)
    typer.echo(f"load {competencias[0]}..{competencias[-1]} - ainda não implementado")


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
