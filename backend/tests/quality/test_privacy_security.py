import json
from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.api.v1.settings import get_settings_service
from app.api.v1.imports import get_import_service
from app.api.v1.my_account import get_my_account_service
from app.api.v1.trends import get_trend_explorer_service
from app.api.v1.competitors import get_competitor_service
from app.api.v1.gap_analysis import get_gap_analysis_service
from app.api.v1.overview import get_overview_service
from app.api.v1.insights import get_insight_service
from app.services.settings_service import SettingsService
from app.services.my_account_service import MyAccountService
from app.services.trend_explorer_service import TrendExplorerService
from app.services.competitor_service import CompetitorService
from app.services.gap_analysis_service import GapAnalysisService
from app.services.overview_service import OverviewService
from app.services.openai_insight_client import AIConfig, OpenAIInsightClient
from app.db.models import AIInsight
from tests.insights.test_api import BODY
from tests.my_account.test_api import add_post
from tests.competitors.test_api import instagram

DEPENDENCIES = [get_settings_service, get_import_service, get_my_account_service,
    get_trend_explorer_service, get_competitor_service, get_gap_analysis_service,
    get_overview_service, get_insight_service]


@pytest.fixture
def client(context, service):
    instances = [SettingsService(context.factory), context.service, MyAccountService(context.factory),
        TrendExplorerService(context.factory), CompetitorService(context.factory),
        GapAnalysisService(context.factory), OverviewService(context.factory), service]
    for dependency, instance in zip(DEPENDENCIES, instances):
        def provide(value):
            def dependency_override(): return value
            return dependency_override
        app.dependency_overrides[dependency] = provide(instance)
    try:
        with TestClient(app) as client: yield client
    finally:
        for dependency in DEPENDENCIES: app.dependency_overrides.pop(dependency, None)


def test_key_absent_never_queries_or_builds_snapshot(client, context, service, monkeypatch):
    service.client = OpenAIInsightClient(AIConfig())
    def forbidden(*args, **kwargs): pytest.fail('Key missing must fail before DB/Overview')
    monkeypatch.setattr(service, 'session_factory', forbidden)
    monkeypatch.setattr(service, 'overview_in_session', forbidden)
    response = client.post(f'/api/v1/projects/{context.project_id}/insights/generate', json=BODY)
    assert response.status_code == 503 and response.json()['error']['code'] == 'AI_KEY_NOT_CONFIGURED'
    assert client.post('/api/v1/projects/PRIVATE_UUID/insights/generate', json=BODY).status_code == 422


def test_external_project_id_removed_internal_audit_and_evidence_retained(client, context, fake):
    add_post(context, text='PRIVATE_POST_BODY', author_name='PRIVATE_AUTHOR',
        raw_data={'password': 'PRIVATE_SECRET'}, metrics={'reach': 0, 'likes': 0})
    response = client.post(f'/api/v1/projects/{context.project_id}/insights/generate', json=BODY)
    assert response.status_code == 201, response.text
    result = response.json()
    summary, evidence = fake.calls[0]
    assert 'project_id' not in summary['analysis_scope']
    external = json.dumps(fake.calls[0], ensure_ascii=False)
    for forbidden in [str(context.project_id), 'PRIVATE_POST_BODY', 'PRIVATE_AUTHOR', 'PRIVATE_SECRET',
                      'account_name', 'display_name', 'raw_data', 'raw_metrics']:
        assert forbidden not in external
    assert summary['analysis_scope']['timezone'] == 'UTC'
    assert result['input_summary']['analysis_scope']['project_id'] == str(context.project_id)
    assert evidence == result['evidence']
    with context.factory() as session:
        saved = session.scalar(select(AIInsight).where(AIInsight.project_id == context.project_id))
        assert saved.input_summary == result['input_summary'] and saved.evidence == evidence


def test_cross_screen_values_preserved_with_different_published_orders(client, context):
    from app.db.models import SNSAccount
    _, comp_ig = instagram(context)
    with context.factory() as session, session.begin():
        session.get(SNSAccount, comp_ig).account_name = 'zzz_phase13_competitor'
    insight = client.post(f'/api/v1/projects/{context.project_id}/insights/generate', json=BODY).json()
    summary = insight['input_summary']['competitor_summary']
    comparison = client.get(f'/api/v1/projects/{context.project_id}/competitors/analytics',
        params=dict(BODY, account_ids=f'{context.competitor_id},{comp_ig}')).json()['accounts']
    comparison = [{k: v for k, v in a.items() if k not in ('account_name', 'display_name')}
                  for a in comparison if a['role'] == 'COMPETITOR']
    assert [a['account_id'] for a in summary] == [str(context.competitor_id), str(comp_ig)]
    assert [a['account_id'] for a in comparison] == [str(comp_ig), str(context.competitor_id)]
    assert {a['account_id']: a for a in summary} == {a['account_id']: a for a in comparison}


def request(client, context, screen, pid=None, params=None):
    base = f'/api/v1/projects/{pid or context.project_id}'
    query = dict(BODY, **(params or {}))
    if screen == 'settings': return client.get(base)
    if screen == 'import':
        return client.post(base + '/imports', data={'import_type': 'PRIVATE_ENUM'}, files={'file': ('safe.csv', b'PRIVATE_CSV')})
    routes = {'own': '/accounts/own/analytics', 'trends': '/trends/ranking',
        'competitor': '/competitors/analytics', 'gap': '/gap-analysis',
        'overview': '/dashboard/overview', 'ai': '/insights/latest'}
    if screen == 'trends': query['topic_id'] = str(context.topic_id)
    if screen == 'competitor': query['account_ids'] = str(context.competitor_id)
    return client.get(base + routes[screen], params=query)


@pytest.mark.parametrize('screen', ['settings', 'import', 'own', 'trends', 'competitor', 'gap', 'overview', 'ai'])
def test_uuid_validation_across_all_apis(client, context, screen, caplog):
    response = request(client, context, screen, pid='PRIVATE_UUID')
    assert response.status_code == 422
    assert 'PRIVATE_UUID' not in response.text + caplog.text


@pytest.mark.parametrize('screen', ['own', 'trends', 'competitor', 'gap', 'overview', 'ai'])
@pytest.mark.parametrize('params,status', [({'platform': 'PRIVATE_ENUM'}, 422),
    ({'from': '2026-10-04', 'to': '2026-10-01'}, 400),
    ({'from': '2000-01-01'}, 400), ({'from': 'PRIVATE_DATE'}, 422)])
def test_period_enum_sanitized(client, context, screen, params, status, caplog):
    response = request(client, context, screen, params=params)
    assert response.status_code == status
    assert 'PRIVATE_' not in response.text + caplog.text


@pytest.mark.parametrize('screen', ['settings', 'own', 'trends', 'competitor', 'gap', 'overview', 'ai'])
def test_unknown_project_safe(client, context, screen):
    assert request(client, context, screen, pid=uuid4()).status_code == 404


@pytest.mark.parametrize('screen,status', [('own', 200), ('trends', 200), ('competitor', 404),
    ('gap', 404), ('overview', 404), ('ai', 404)])
def test_disabled_platform_preserves_existing_contract(client, context, screen, status):
    # Phase7/8 return scoped Empty, later APIs use 404. Do not cosmetically unify.
    response = request(client, context, screen, params={'platform': 'INSTAGRAM'})
    assert response.status_code == status


@pytest.mark.parametrize('screen,dependency', list(zip(
    ['settings', 'import', 'own', 'trends', 'competitor', 'gap', 'overview', 'ai'], DEPENDENCIES)))
def test_unexpected_dependency_failure_has_no_response_or_log_leak(client, context, screen, dependency, caplog):
    def broken(): raise RuntimeError('SELECT password=PRIVATE_SECRET C:/private/file.csv Python traceback raw response')
    app.dependency_overrides[dependency] = broken
    response = request(client, context, screen)
    assert response.status_code == 500
    for forbidden in ['PRIVATE_SECRET', 'SELECT', 'C:/private', 'traceback', 'raw response']:
        assert forbidden not in response.text + caplog.text
