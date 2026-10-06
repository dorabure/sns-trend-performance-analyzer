import base64
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import delete, event, select

from app.api.v1.insights import get_insight_history_service
from app.db.models import AIInsight, Project
from app.main import app
from app.services.insight_history_service import InsightHistoryService, input_summary_hash
from tests.insights.conftest import content
from tests.insights.test_api import BODY, generate, latest, rows

NOW = datetime(2026, 10, 5, 1, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def history_dependency(context):
    app.dependency_overrides[get_insight_history_service] = lambda: InsightHistoryService(context.factory)
    yield
    app.dependency_overrides.pop(get_insight_history_service, None)


@pytest.fixture
def live_project(context):
    with context.factory() as s, s.begin():
        project = Project(name='History isolated Live', data_mode='LIVE')
        s.add(project)
        s.flush()
        pid = project.project_id
    yield pid
    with context.factory() as s, s.begin():
        s.execute(delete(Project).where(Project.project_id == pid))


def add(c, number=1, **overrides):
    values = dict(insight_id=UUID(int=number), project_id=c.project_id, platform='X',
        analysis_from=date(2026, 10, 1), analysis_to=date(2026, 10, 3), created_at=NOW,
        content=content().model_dump(mode='json'),
        evidence=dict(kpis=[], trends=[], competitors=[], opportunities=[]),
        input_summary={'日本語': {'zero': 0, 'unknown': None}}, model_name='fixture', prompt_version='v1')
    values.update(overrides)
    with c.factory() as s, s.begin():
        s.add(AIInsight(**values))
    return str(values['insight_id'])


def path(c, suffix='', project=None):
    return f'/api/v1/projects/{project or c.project_id}/insights/history{suffix}'


def get(client, c, suffix='', params=None, project=None):
    response = client.get(path(c, suffix, project), params=params)
    assert response.status_code == 200, response.text
    return response.json()


def digest(c):
    with c.factory() as s:
        data = [dict(r) for r in s.execute(select(AIInsight.__table__).order_by(AIInsight.insight_id)).mappings()]
    return len(data), hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def test_empty_default_page(client, context):
    assert get(client, context) == {'items': [], 'next_cursor': None}


def test_order_timestamps_then_uuid_and_lightweight_metadata(client, context):
    oldest = add(context, 9, created_at=NOW - timedelta(seconds=1))
    middle = add(context, 1)
    newest = add(context, 2)
    items = get(client, context)['items']
    assert [r['insight_id'] for r in items] == [newest, middle, oldest]
    assert items[0]['data_mode'] == 'DEMO' and items[0]['platform'] == 'X'
    assert not items[0]['is_legacy'] and len(items[0]['input_summary_hash']) == 64
    assert not {'content', 'evidence', 'input_summary', 'sections'} & items[0].keys()


def test_three_pages_no_duplicate_or_missing_and_insert_above_boundary(client, context):
    ids = [add(context, n) for n in range(1, 7)]
    first = get(client, context, params={'limit': 2})
    add(context, 10, created_at=NOW + timedelta(seconds=1))
    second = get(client, context, params={'limit': 2, 'cursor': first['next_cursor']})
    third = get(client, context, params={'limit': 2, 'cursor': second['next_cursor']})
    collected = [r['insight_id'] for p in [first, second, third] for r in p['items']]
    assert collected == list(reversed(ids)) and len(set(collected)) == 6
    assert third['next_cursor'] is None


@pytest.mark.parametrize('platform,expected', [('X', [1]), ('ALL', [2]), ('INSTAGRAM', [3])])
def test_platform_exact_filter(client, context, platform, expected):
    for n, p in [(1, 'X'), (2, None), (3, 'INSTAGRAM')]:
        add(context, n, platform=p)
    assert [r['insight_id'] for r in get(client, context, params={'platform': platform})['items']] == [str(UUID(int=n)) for n in expected]


def test_period_is_exact_analysis_scope_and_latest_matches(client, context):
    add(context, 1)
    add(context, 2, analysis_to=date(2026, 10, 4))
    add(context, 3, platform=None)
    add(context, 4, platform=None)
    page = get(client, context, params=BODY)
    assert [r['insight_id'] for r in page['items']] == [str(UUID(int=4)), str(UUID(int=3))]
    assert latest(client, context)['insight']['insight_id'] == page['items'][0]['insight_id']


def test_project_and_data_mode_isolation(client, context, live_project):
    own = add(context, 1)
    remote = add(context, 2, project_id=live_project)
    add(context, 3, project_id=live_project, platform='INSTAGRAM')
    assert [r['insight_id'] for r in get(client, context)['items']] == [own]
    page = get(client, context, project=live_project)
    assert len(page['items']) == 2 and all(r['data_mode'] == 'LIVE' for r in page['items'])
    assert get(client, context, '/' + remote, project=live_project)['data_mode'] == 'LIVE'


@pytest.mark.parametrize('suffix', ['', '/compare-previous'])
def test_cross_project_and_missing_detail_hidden(client, context, live_project, suffix):
    remote = add(context, 1, project_id=live_project)
    for iid in [remote, str(uuid4())]:
        response = client.get(path(context, '/' + iid + suffix))
        assert response.status_code == 404 and response.json()['error']['code'] == 'NOT_FOUND'


@pytest.mark.parametrize('suffix', ['', '/00000000-0000-0000-0000-000000000001',
                                     '/00000000-0000-0000-0000-000000000001/compare-previous'])
def test_missing_project(client, context, suffix):
    assert client.get(path(context, suffix, uuid4())).status_code == 404


def test_complete_detail_and_hash(client, context):
    iid = add(context)
    result = get(client, context, '/' + iid)
    assert result['content']['summary'] == '架空テスト要約'
    assert result['input_summary_hash'] == input_summary_hash(result['input_summary'])
    assert result['model_name'] == 'fixture' and result['prompt_version'] == 'v1'
    assert result['generated_at'] == NOW.isoformat().replace('+00:00', 'Z')


def test_previous_sequence_including_same_timestamp_and_first(client, context):
    ids = [add(context, n) for n in [1, 2, 3]]
    for n in [2, 1, 0]:
        result = get(client, context, '/' + ids[n] + '/compare-previous')
        assert result['current']['insight_id'] == ids[n]
        if n:
            assert result['previous']['insight_id'] == ids[n - 1]
            assert result['comparison']['has_previous'] and result['comparison']['changed'] is False
            assert result['comparison']['generated_at_delta_seconds'] == 0
        else:
            assert result['previous'] is None
            assert result['comparison']['has_previous'] is False
            assert all(v is None for k, v in result['comparison'].items() if k != 'has_previous')


def test_previous_excludes_other_project_platform_period_and_later(client, context, live_project):
    previous = add(context, 1, created_at=NOW - timedelta(seconds=5))
    current = add(context, 9)
    for n, change in [(2, {'project_id': live_project}), (3, {'platform': None}),
                      (4, {'platform': 'INSTAGRAM'}), (5, {'analysis_from': date(2026, 9, 30)}),
                      (6, {'analysis_to': date(2026, 10, 4)}), (10, {})]:
        add(context, n, **change)
    result = get(client, context, '/' + current + '/compare-previous')
    assert result['previous']['insight_id'] == previous
    assert result['comparison']['generated_at_delta_seconds'] == 5


@pytest.mark.parametrize('field,change,flag', [
    ('input_summary', {'日本語': 1}, 'input_changed'),
    ('prompt_version', 'v2', 'prompt_version_changed'),
    ('model_name', None, 'model_changed'),
    ('content', content('変化').model_dump(mode='json'), 'content_changed'),
    ('evidence', {'kpis': [], 'trends': [], 'competitors': [], 'opportunities': [{'id': 'x', 'label': 'x', 'values': {}}]}, 'evidence_changed')])
def test_comparison_flags_are_independent(client, context, field, change, flag):
    add(context, 1)
    iid = add(context, 2, **{field: change})
    comparison = get(client, context, '/' + iid + '/compare-previous')['comparison']
    assert comparison['changed'] is True and comparison[flag] is True
    assert all(v is False for k, v in comparison.items() if k.endswith('_changed') and k != flag)


def test_reads_no_mutation_no_external_http_no_ai_client(client, context, monkeypatch):
    iid = add(context, 1)
    add(context, 2)
    before = digest(context)
    calls = []
    def blocked(*args, **kwargs):
        calls.append(True)
        raise AssertionError('History must not call any external client')
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', blocked)
    monkeypatch.setattr('app.services.insight_service.OpenAIInsightClient', blocked)
    for suffix in ['', '/' + iid, '/' + iid + '/compare-previous']:
        get(client, context, suffix)
    assert not calls and digest(context) == before


def test_legacy_all_read_paths_and_raw_row_unchanged(client, context):
    old = dict(market_trend='旧市場', own_analysis='旧分析', improvement_points=[], post_ideas=[])
    iid = add(context, 1, platform=None, content=old, evidence={'old': ['旧根拠']})
    current = add(context, 2, platform=None)
    before = digest(context)
    assert get(client, context)['items'][1]['is_legacy'] is True
    detail = get(client, context, '/' + iid)
    assert detail['is_legacy'] and detail['content'] is None and detail['legacy_evidence'] == {'old': ['旧根拠']}
    assert get(client, context, '/' + current + '/compare-previous')['previous']['is_legacy']
    assert get(client, context, '/' + iid + '/compare-previous')['previous'] is None
    assert digest(context) == before
    # Latest legacy remains readable without changing the stored row.
    with context.factory() as s, s.begin():
        s.execute(delete(AIInsight).where(AIInsight.insight_id == UUID(current)))
    assert latest(client, context)['insight']['content'] is None
    with context.factory() as s:
        row = s.get(AIInsight, UUID(iid))
        assert row.content == old and row.evidence == {'old': ['旧根拠']}


def test_generate_append_only_history_and_latest_regression(client, context, fake):
    first = generate(client, context)
    before = rows(context)[0].content.copy()
    fake.result = content('新しい結果')
    second = generate(client, context)
    assert len(rows(context)) == 2 and rows(context)[0].content == before
    assert [r['insight_id'] for r in get(client, context, params=BODY)['items']] == [second['insight_id'], first['insight_id']]
    assert latest(client, context)['insight']['insight_id'] == second['insight_id']


@pytest.mark.parametrize('params,status', [({'limit': 0}, 422), ({'limit': 101}, 422),
    ({'limit': 'abc'}, 422), ({'platform': 'TIKTOK'}, 422), ({'from': 'bad', 'to': '2026-10-01'}, 422),
    ({'from': '2026-10-01'}, 422), ({'to': '2026-10-01'}, 422),
    ({'from': '2026-10-03', 'to': '2026-10-01'}, 400), ({'cursor': 'bad'}, 422),
    ({'cursor': base64.urlsafe_b64encode(b'{}').decode()}, 422), ({'cursor': 'a' * 1025}, 422),
    ({'cursor': ''}, 422)])
def test_invalid_requests_use_safe_envelope(client, context, params, status):
    response = client.get(path(context), params=params)
    assert response.status_code == status and 'error' in response.json()
    assert set(response.json()['error']) == {'code', 'message', 'details'}


def test_cursor_scope_binding(client, context, live_project):
    add(context, 1)
    add(context, 2)
    cursor = get(client, context, params={'limit': 1})['next_cursor']
    assert client.get(path(context), params={'cursor': cursor, 'platform': 'X'}).status_code == 422
    assert client.get(path(context, project=live_project), params={'cursor': cursor}).status_code == 422


def test_page_query_count_constant_not_n_plus_one(client, context):
    for n in range(1, 8):
        add(context, n)
    with context.factory() as s:
        engine = s.get_bind()
    queries = []
    def track(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('SELECT'):
            queries.append(statement)
    event.listen(engine, 'before_cursor_execute', track)
    try:
        assert len(get(client, context, params={'limit': 5})['items']) == 5
    finally:
        event.remove(engine, 'before_cursor_execute', track)
    assert len(queries) == 2 and 'LIMIT' in queries[1]


def test_default_limit_twenty(client, context):
    for n in range(1, 23):
        add(context, n)
    page = get(client, context)
    assert len(page['items']) == 20 and page['next_cursor']


def test_input_hash_canonical_utf8_and_changed_values():
    a = {'日本語': {'b': 0, 'a': None}, 'items': [1, 2]}
    b = {'items': [1, 2], '日本語': {'a': None, 'b': 0}}
    assert input_summary_hash(a) == input_summary_hash(b)
    expected = hashlib.sha256(json.dumps(a, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()
    assert input_summary_hash(a) == expected
    assert input_summary_hash(a) != input_summary_hash(dict(a, items=[2, 1]))
