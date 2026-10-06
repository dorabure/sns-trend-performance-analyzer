import pytest
from fastapi.testclient import TestClient

from app.api.v1.trends import get_trend_explorer_service
from app.main import app
from app.services.trend_explorer_service import TrendExplorerService
from tests.imports.conftest import context  # noqa: F401


@pytest.fixture
def service(context):
    return TrendExplorerService(context.factory)


@pytest.fixture
def client(service):
    app.dependency_overrides[get_trend_explorer_service] = lambda: service
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_trend_explorer_service, None)
