"""Test-only database lifecycle; cannot downgrade or drop the application DB."""
import re
import uuid
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


def validate_test_database(name: str, application_database: str) -> None:
    if not re.fullmatch(r"sns_phase2_test_[0-9a-f]{32}", name) or name == application_database:
        raise ValueError("Refusing destructive operation on a non-disposable database")


@contextmanager
def disposable_database():
    application_url = get_settings().database_url
    name = f"sns_phase2_test_{uuid.uuid4().hex}"
    validate_test_database(name, application_url.database)
    admin = create_engine(application_url.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool)
    engine = None
    created = False
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        created = True
        engine = create_engine(application_url.set(database=name), poolclass=NullPool)
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            validate_test_database(name, application_url.database)
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


def alembic_config():
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    return config


def migrate(engine, operation, revision):
    if operation == "downgrade":
        validate_test_database(engine.url.database, get_settings().database_url.database)
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        getattr(command, operation)(config, revision)
