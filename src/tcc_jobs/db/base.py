from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Sem convenção de nomes, o autogenerate cria constraints anônimas, e o
# downgrade falha com "Can't emit DROP CONSTRAINT ... it has no name". Nomes
# determinísticos tornam as migrations reversíveis.
CONVENCAO_NOMES = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base declarativa de todos os modelos."""

    metadata = MetaData(naming_convention=CONVENCAO_NOMES)
