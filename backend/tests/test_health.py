from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.main import app


@pytest.fixture
def db():
    return MagicMock(spec=Session)


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_health_success(client, db):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}
    assert response.headers["cache-control"] == "no-store"
    assert str(db.execute.call_args.args[0]) == "SELECT 1"


def test_database_failure_returns_503_without_secrets(client, db):
    db.execute.side_effect = OperationalError("SELECT 1", {}, Exception("secret_password"))
    response = client.get("/api/v1/health", headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "disconnected"}
    assert "secret_password" not in response.text
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_allowed_origin(client):
    response = client.get("/api/v1/health", headers={"Origin": "http://localhost:3000"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_unlisted_origin(client):
    response = client.get("/api/v1/health", headers={"Origin": "https://unlisted.example"})
    assert "access-control-allow-origin" not in response.headers


def test_cors_preflight(client):
    response = client.options("/api/v1/health", headers={
        "Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET",
    })
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_sqlalchemy_executes_real_query(client):
    # A real lightweight SQL execution test, not a PostgreSQL integration test.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    with Session(engine) as session:
        app.dependency_overrides[get_db] = lambda: session
        assert client.get("/api/v1/health").json() == {"status": "ok", "database": "connected"}
    engine.dispose()
