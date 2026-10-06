import pytest
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from app.main import app
from app.demo.loader import load
from app.services.openai_insight_client import AIConfig,OpenAIInsightClient
from tests.postgres_support import disposable_database,migrate

@pytest.fixture(scope="module")
def demo():
    with disposable_database() as engine:
        migrate(engine,"upgrade","head")
        factory=sessionmaker(engine,expire_on_commit=False)
        result=load(factory)
        yield factory,engine,result

@pytest.fixture
def client(demo):
    factory,_,_=demo
    from app.api.v1.settings import get_settings_service
    from app.api.v1.imports import get_import_service
    from app.api.v1.my_account import get_my_account_service
    from app.api.v1.trends import get_trend_explorer_service
    from app.api.v1.competitors import get_competitor_service
    from app.api.v1.gap_analysis import get_gap_analysis_service
    from app.api.v1.overview import get_overview_service
    from app.api.v1.insights import get_insight_service
    from app.services.settings_service import SettingsService
    from app.services.import_service import ImportService
    from app.services.my_account_service import MyAccountService
    from app.services.trend_explorer_service import TrendExplorerService
    from app.services.competitor_service import CompetitorService
    from app.services.gap_analysis_service import GapAnalysisService
    from app.services.overview_service import OverviewService
    from app.services.insight_service import InsightService
    bindings={get_settings_service:SettingsService(factory),get_import_service:ImportService(factory),
        get_my_account_service:MyAccountService(factory),get_trend_explorer_service:TrendExplorerService(factory),
        get_competitor_service:CompetitorService(factory),get_gap_analysis_service:GapAnalysisService(factory),
        get_overview_service:OverviewService(factory),get_insight_service:InsightService(factory,OpenAIInsightClient(AIConfig()))}
    def provider(service):
        def provide(): return service
        return provide
    old=dict(app.dependency_overrides)
    app.dependency_overrides.update({dep:provider(service) for dep,service in bindings.items()})
    try:
        with TestClient(app) as c: yield c
    finally: app.dependency_overrides.clear();app.dependency_overrides.update(old)
