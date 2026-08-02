# tcc-jobs

Camada de dados e IA do TCC — Sistema Inteligente para Licitações.

Python em lote: baixa os CSVs do Portal da Transparência, normaliza, carrega no
PostgreSQL, treina os modelos de previsão e calcula scores de anomalia.
Todos os resultados são materializados em tabelas — a API apenas lê.

**Dono do esquema do banco.** As migrations Alembic aqui são a única fonte de verdade.

## Requisitos

- Python 3.12+, [uv](https://docs.astral.sh/uv/)
- PostgreSQL 16 acessível (ver `../tcc-infra`)

## Uso

```bash
uv sync
uv run alembic upgrade head
uv run tcc ingest --de 201301 --ate 202404
uv run tcc load   --de 201301 --ate 202404
uv run tcc aggregate
uv run tcc train --serie orgao
uv run tcc score
```

## Documentação

`../brain/content/10_Dev/licitacoes-pipeline-etl.md` e `licitacoes-modelos-ia.md`.
