"""índice de busca textual no objeto da licitação

Revision ID: f3a91c72b104
Revises: dbdfe5415a3a
Create Date: 2026-08-18 18:10:00.000000

A API busca no objeto com `ILIKE '%termo%'`, que um índice B-tree não atende:
o curinga à esquerda impede o uso da árvore. Medido na base cheia, a consulta
fazia Parallel Seq Scan sobre 235 MB de texto em 1,74 milhão de linhas.

| | Sem índice | Com trigram |
|---|---|---|
| Consulta no banco | 1.137 ms | 10 ms |
| Endpoint completo | 2.609 ms | 57 ms |

O índice GIN ocupa 306 MB e leva ~104 s para criar. Vale: sem ele o endpoint
de consulta fica 8x acima do orçamento de 300 ms sempre que o filtro de texto
é usado.

A extensão pg_trgm é criada aqui porque o Alembic é o dono do esquema - o
tcc-api não pode criá-la sem quebrar essa propriedade.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f3a91c72b104"
down_revision: str | Sequence[str] | None = "dbdfe5415a3a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE INDEX ix_licitacao_objeto_trgm ON licitacao USING gin (objeto gin_trgm_ops)")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_licitacao_objeto_trgm")
    # A extensão fica: outra coisa pode passar a depender dela, e removê-la
    # em cascata derrubaria índices que não são desta migration.
