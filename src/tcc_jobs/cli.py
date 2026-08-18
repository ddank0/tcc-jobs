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
    forcar_download: bool = typer.Option(False, help="Ignora o cache em bronze"),
) -> None:
    """Baixa os ZIPs e grava Parquet limpo em silver."""
    # Import tardio: mantém a CLI leve e evita que importar cli arraste Polars
    # e httpx para comandos que não precisam deles.
    from tcc_jobs.core.config import settings
    from tcc_jobs.etl.armazenamento import Armazenamento
    from tcc_jobs.etl.pipeline import ingerir
    from tcc_jobs.portal.client import ClienteHttpPortal

    competencias = _intervalo(de, ate)
    resultados = ingerir(
        competencias,
        ClienteHttpPortal(),
        Armazenamento(settings.data_dir),
        forcar_download=forcar_download,
    )

    com_erro = [r for r in resultados if r.erro]
    total = sum(sum(r.linhas_por_tabela.values()) for r in resultados)
    do_cache = sum(1 for r in resultados if r.veio_do_cache)

    typer.echo(
        f"{len(resultados) - len(com_erro)}/{len(resultados)} competências, "
        f"{total} linhas em silver ({do_cache} do cache)"
    )
    for r in com_erro:
        typer.echo(f"  {r.competencia}: {r.erro}", err=True)

    # Recuperação parcial não é erro, mas deixa lacuna no dado - e lacuna
    # silenciosa vira conclusão errada lá na frente.
    for r in (x for x in resultados if x.recuperacao_parcial):
        ausentes = ", ".join(r.tabelas_ausentes) or "nenhuma tabela"
        typer.echo(f"  {r.competencia}: ZIP corrompido na origem, sem {ausentes}", err=True)


@app.command()
def load(
    de: str = typer.Option(..., help="Competência inicial, AAAAMM"),
    ate: str = typer.Option(..., help="Competência final, AAAAMM"),
    carga_inicial: bool = typer.Option(
        False,
        help="Remove as chaves estrangeiras durante o INSERT. Exige banco fora de uso.",
    ),
) -> None:
    """Carrega silver no PostgreSQL via COPY."""
    from tcc_jobs.core.config import settings
    from tcc_jobs.db.carga import carregar
    from tcc_jobs.db.session import criar_engine
    from tcc_jobs.etl.armazenamento import Armazenamento

    if carga_inicial:
        # O DROP CONSTRAINT precisa de ACCESS EXCLUSIVE e trava qualquer leitura
        # concorrente - a API inclusive. O aviso é o que impede o uso distraído.
        typer.echo("carga-inicial: as chaves estrangeiras saem durante o INSERT.", err=True)
        typer.echo("O banco precisa estar fora de uso - a API travaria.", err=True)

    competencias = _intervalo(de, ate)
    resultados = carregar(
        competencias,
        Armazenamento(settings.data_dir),
        criar_engine(settings.database_url),
        carga_inicial=carga_inicial,
    )

    com_erro = [r for r in resultados if r.erro]
    total = sum(r.inseridas.get("licitacao", 0) for r in resultados)

    typer.echo(
        f"{len(resultados) - len(com_erro)}/{len(resultados)} competências, "
        f"{total} licitações carregadas"
    )
    for r in com_erro:
        typer.echo(f"  {r.competencia}: {r.erro}", err=True)


@app.command()
def aggregate() -> None:
    """Monta as tabelas agregadas que a API serve."""
    from tcc_jobs.core.config import settings
    from tcc_jobs.db.agregacao_carga import agregar, agregar_fornecedores
    from tcc_jobs.db.session import criar_engine
    from tcc_jobs.etl.armazenamento import Armazenamento

    engine = criar_engine(settings.database_url)

    total = agregar(engine)
    typer.echo(f"serie_mensal: {total} linhas")

    por_competencia, global_ = agregar_fornecedores(engine, Armazenamento(settings.data_dir))
    typer.echo(f"ranking_fornecedor: {por_competencia} linhas")
    typer.echo(f"ranking_fornecedor_total: {global_} linhas")


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
