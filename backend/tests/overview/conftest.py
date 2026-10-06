import pytest
from fastapi.testclient import TestClient

from app.api.v1.overview import get_overview_service
from app.api.v1.my_account import get_my_account_service
from app.api.v1.gap_analysis import get_gap_analysis_service
from app.api.v1.competitors import get_competitor_service
from app.main import app
from app.services.overview_service import OverviewService
from app.services.my_account_service import MyAccountService
from app.services.gap_analysis_service import GapAnalysisService
from app.services.competitor_service import CompetitorService
from tests.imports.conftest import context


@pytest.fixture
def client(context):
    dependencies = {
        get_overview_service: OverviewService, get_my_account_service: MyAccountService,
        get_gap_analysis_service: GapAnalysisService, get_competitor_service: CompetitorService}
    for dependency, service in dependencies.items():
        app.dependency_overrides[dependency] = lambda service=service: service(context.factory)
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        for dependency in dependencies:
            app.dependency_overrides.pop(dependency, None)
