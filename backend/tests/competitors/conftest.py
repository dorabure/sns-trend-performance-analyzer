import pytest
from fastapi.testclient import TestClient

from app.api.v1.competitors import get_competitor_service
from app.main import app
from app.services.competitor_service import CompetitorService
from tests.imports.conftest import context  # isolated PostgreSQL Project, cascading cleanup


@pytest.fixture
def client(context):
    app.dependency_overrides[get_competitor_service] = lambda: CompetitorService(context.factory)
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_competitor_service, None)
