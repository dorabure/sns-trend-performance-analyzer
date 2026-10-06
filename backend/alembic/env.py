from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import get_settings
from app.db import models  # noqa: F401
from app.db.base import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
target_metadata = Base.metadata


def run_with_connection(connection):
    context.configure(
        connection=connection, target_metadata=target_metadata,
        compare_type=True, compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(
        url=get_settings().database_url, target_metadata=target_metadata,
        literal_binds=True, dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    # Tests supply a connection to an explicitly created disposable database.
    connection = config.attributes.get("connection")
    if connection is not None:
        run_with_connection(connection)
    else:
        engine = create_engine(get_settings().database_url, poolclass=pool.NullPool)
        try:
            with engine.connect() as connection:
                run_with_connection(connection)
        finally:
            engine.dispose()
