"""Phase 11 browser-only fixture; production never imports this module.

Run in a temporary container with all provider gates off. Normal shutdown drops
the validated disposable database. All reports and evidence are fictional.
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from time import sleep
from uuid import UUID

import httpx
import uvicorn
from fastapi.responses import JSONResponse
from sqlalchemy.orm import sessionmaker

from app.api.v1.insights import get_insight_service, get_insight_history_service
from app.api.v1.overview import get_overview_service
from app.api.v1.settings import get_settings_service
from app.db.models import AIInsight, Project, ProjectPlatform
from app.main import app
from app.services.insight_service import InsightService
from app.services.insight_history_service import InsightHistoryService
from app.services.overview_service import OverviewService
from app.services.settings_service import SettingsService
from app.services.openai_insight_client import failure
from tests.insights.conftest import content
from tests.postgres_support import disposable_database, migrate

PROJECT = UUID('00000000-0000-4000-8000-000000000011')
EMPTY = UUID('00000000-0000-4000-8000-000000000012')
HISTORY_ERROR = UUID('00000000-0000-4000-8000-000000000013')
COMPARE_ERROR = UUID('00000000-0000-4000-8000-000000000014')


def no_external(*args, **kwargs):
    raise AssertionError('External HTTP is forbidden in this browser fixture')


class BrowserClient:
    available = True

    def __init__(self):
        self.calls = 0

    def generate(self, summary, evidence):
        sleep(2)
        self.calls += 1
        if self.calls == 3:
            raise failure('AI_TIMEOUT', 'AI analysis timed out')
        return content(f'Fake Fixture generated report {self.calls}'), 'demo-fixture'


failures = set()


@app.middleware('http')
async def controlled_responses(request, call_next):
    path = request.url.path
    history_failure = str(HISTORY_ERROR) in path and path.endswith('/history')
    compare_failure = str(COMPARE_ERROR) in path and path.endswith('/compare-previous')
    if (history_failure or compare_failure) and path not in failures:
        failures.add(path)
        return JSONResponse(status_code=503, content={'error': {
            'code': 'AI_TIMEOUT', 'message': 'Fictional controlled failure', 'details': []}})
    if path.endswith('/history') and request.query_params.get('platform') == 'INSTAGRAM':
        await asyncio.sleep(4)
    if path.endswith('/00000000-0000-0000-0000-000000000003/compare-previous'):
        await asyncio.sleep(2)
    return await call_next(request)


@asynccontextmanager
async def lifespan(application):
    httpx.HTTPTransport.handle_request = no_external
    httpx.AsyncHTTPTransport.handle_async_request = no_external
    with disposable_database() as engine:
        migrate(engine, 'upgrade', 'head')
        factory = sessionmaker(engine, expire_on_commit=False)
        with factory() as session, session.begin():
            for pid, name in [(PROJECT, 'Phase11 Fake History'), (EMPTY, 'Phase11 Empty'),
                              (HISTORY_ERROR, 'Phase11 History Retry'), (COMPARE_ERROR, 'Phase11 Compare Retry')]:
                session.add(Project(project_id=pid, name=name))
            session.flush()
            for pid in [PROJECT, EMPTY, HISTORY_ERROR, COMPARE_ERROR]:
                session.add(ProjectPlatform(project_id=pid, platform='X'))
            session.add(ProjectPlatform(project_id=PROJECT, platform='INSTAGRAM'))
            for pid, numbers in [(PROJECT, range(1, 13)), (HISTORY_ERROR, [101]), (COMPARE_ERROR, [201])]:
                for number in numbers:
                    legacy = number == 1
                    report = content(f'Fake Fixture saved report {2 if number == 3 else number}').model_dump(mode='json')
                    if legacy:
                        report = {key: report[key] for key in ['market_trend', 'own_analysis', 'improvement_points', 'post_ideas']}
                    session.add(AIInsight(insight_id=UUID(int=number), project_id=pid, platform=None,
                        analysis_from=date(2026, 10, 1), analysis_to=date(2026, 10, 3),
                        created_at=datetime(2026, 10, 5, 0, tzinfo=timezone.utc) + timedelta(minutes=number),
                        content=report, evidence={'fixture': True} if legacy else {
                            'kpis': [{'id': 'KPI_REACH', 'label': 'reach', 'values': {'value': 0}}],
                            'trends': [], 'competitors': [], 'opportunities': []},
                        input_summary={'fixture': True, 'zero': 0, 'unknown': None},
                        model_name='demo-fixture', prompt_version='phase11-fixture'))
        client = BrowserClient()
        application.dependency_overrides[get_insight_service] = lambda: InsightService(factory, client)
        application.dependency_overrides[get_insight_history_service] = lambda: InsightHistoryService(factory)
        application.dependency_overrides[get_settings_service] = lambda: SettingsService(factory)
        application.dependency_overrides[get_overview_service] = lambda: OverviewService(factory)
        print('PHASE11_BROWSER_FIXTURE_READY real_external_calls=0', flush=True)
        try:
            yield
        finally:
            application.dependency_overrides.clear()


if __name__ == '__main__':
    app.router.lifespan_context = lifespan
    uvicorn.run(app, host='0.0.0.0', port=8000)
