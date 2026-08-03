from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from tcc_jobs.core.config import settings
from tcc_jobs.db import models
from tcc_jobs.db.base import Base

config = context.config

# A URL vem da configuração da aplicação, não do alembic.ini. Mas só é
# definida se o chamador ainda não tiver escolhido uma: os testes passam a
# URL do banco de teste, e sobrescrevê-la aqui faria a migration rodar no
# banco de desenvolvimento sem avisar.
if not config.get_main_option("sqlalchemy.url", None):
    config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# O import de models não é usado diretamente, mas é o que registra as tabelas
# no metadata. Sem ele, o autogenerate produz uma migration que não cria nada.
# A atribuição torna a dependência explícita para o linter e o type checker,
# em vez de exigir uma supressão para cada ferramenta.
_ = models

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
