import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from app.db.base import Base
from app.db.models import *  # Register every model for migration comparison.
from tests.postgres_support import alembic_config, disposable_database, migrate, validate_test_database


def test_empty_upgrade_downgrade_reupgrade():
    script = ScriptDirectory.from_config(alembic_config())
    assert script.get_heads() == ["0005_v2_provider_core"]
    with disposable_database() as engine:
        assert inspect(engine).get_table_names() == []
        migrate(engine, "upgrade", "head")
        assert set(inspect(engine).get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0005_v2_provider_core"
        migrate(engine, "downgrade", "base")
        assert inspect(engine).get_table_names() == ["alembic_version"]
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM alembic_version")) == 0
        migrate(engine, "upgrade", "head")
        assert len(inspect(engine).get_table_names()) == 19


@pytest.mark.parametrize("name", ["sns_analyzer", "postgres", "unit_test", "sns_phase2_test_bad", 'sns_phase2_test_";DROP DATABASE postgres;--'])
def test_refuse_destructive_non_test_database(name):
    with pytest.raises(ValueError):
        validate_test_database(name, "sns_analyzer")


def test_refuse_application_database_even_with_test_prefix():
    name = "sns_phase2_test_" + "a" * 32
    with pytest.raises(ValueError):
        validate_test_database(name, name)
