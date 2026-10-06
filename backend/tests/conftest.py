import os

# Defaults support isolated health unit tests; integration tests require real credentials.
os.environ.setdefault("POSTGRES_DB", "unit_test")
os.environ.setdefault("POSTGRES_USER", "unit_test")
os.environ.setdefault("POSTGRES_PASSWORD", "unit_test_only")
os.environ.setdefault("POSTGRES_HOST", "127.0.0.1")
os.environ.setdefault("FRONTEND_ORIGIN", "http://localhost:3000")

import pytest
from sqlalchemy.orm import Session

from tests.postgres_support import disposable_database, migrate


@pytest.fixture(autouse=True)
def forbid_external_http_in_regression(monkeypatch):
    import httpx
    def blocked(*args, **kwargs):
        raise AssertionError('External HTTP is forbidden in default regression')
    async def async_blocked(*args, **kwargs):
        raise AssertionError('External HTTP is forbidden in default regression')
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', blocked)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', async_blocked)


@pytest.fixture(autouse=True)
def isolate_startup_recovery(monkeypatch):
    # Existing route/health tests must never recover the developer's database.
    # Phase13 recovery tests exercise the real function and lifespan separately.
    monkeypatch.setattr("app.main.recover_interrupted_imports", lambda factory: 0)


@pytest.fixture(scope="session")
def postgres_engine():
    with disposable_database() as engine:
        migrate(engine, "upgrade", "head")
        yield engine


@pytest.fixture
def database(postgres_engine):
    # Each test has its own rollback boundary, including tests that commit seed.
    with postgres_engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()
