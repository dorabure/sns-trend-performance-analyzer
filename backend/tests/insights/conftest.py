import pytest
from fastapi.testclient import TestClient

from app.api.v1.insights import get_insight_service
from app.api.v1.overview import get_overview_service
from app.api.v1.my_account import get_my_account_service
from app.api.v1.gap_analysis import get_gap_analysis_service
from app.api.v1.competitors import get_competitor_service
from app.main import app
from app.services.insight_service import InsightService
from app.services.overview_service import OverviewService
from app.services.my_account_service import MyAccountService
from app.services.gap_analysis_service import GapAnalysisService
from app.services.competitor_service import CompetitorService
from app.schemas.insights import AIInsightContent
from tests.imports.conftest import context


def content(summary='架空テスト要約', ref='KPI_REACH'):
    return AIInsightContent(summary=summary, market_trend='判断材料不足。', own_analysis='自社分析。',
        improvement_points=['改善案'], post_ideas=['X: 次回投稿テーマ'], cautions=['成果保証なし'],
        references={'market_trend': [ref], 'own_analysis': [ref],
            'improvement_points': [[ref]], 'post_ideas': [[ref]]})


class FakeClient:
    available = True
    def __init__(self):
        self.calls = []
        self.result = content()
        self.error = None
        self.on_call = None

    def generate(self, summary, evidence):
        self.calls.append((summary, evidence))
        if self.on_call:
            self.on_call(summary, evidence)
        if self.error:
            raise self.error
        return self.result, 'fake-response-model'


@pytest.fixture
def fake():
    return FakeClient()


@pytest.fixture
def service(context, fake):
    return InsightService(context.factory, fake)


@pytest.fixture
def client(context, service):
    services = {get_overview_service: OverviewService, get_my_account_service: MyAccountService,
        get_gap_analysis_service: GapAnalysisService, get_competitor_service: CompetitorService}
    app.dependency_overrides[get_insight_service] = lambda: service
    for dependency, cls in services.items():
        app.dependency_overrides[dependency] = lambda cls=cls: cls(context.factory)
    try:
        with TestClient(app) as client:
            yield client
    finally:
        for dependency in [get_insight_service, *services]:
            app.dependency_overrides.pop(dependency, None)
