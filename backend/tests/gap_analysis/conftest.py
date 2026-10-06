import pytest
from fastapi.testclient import TestClient

from app.api.v1.gap_analysis import get_gap_analysis_service
from app.main import app
from app.services.gap_analysis_service import GapAnalysisService
from tests.imports.conftest import context


@pytest.fixture
def client(context):
    app.dependency_overrides[get_gap_analysis_service] = lambda: GapAnalysisService(context.factory)
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_gap_analysis_service, None)
