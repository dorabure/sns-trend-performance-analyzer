from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, insert, text

from app.db.models import (AIInsight, AccountMetric, PostMetric, PostTopic, Project,
    ProjectPlatform, SNSAccount, SNSPost, TrendDaily, WatchTopic)
from app.repositories.overview_repository import OverviewRepository
from app.services.overview_service import OverviewService
from app.services.my_account_service import MyAccountService
from tests.competitors.test_api import account, instagram, match
from tests.gap_analysis.test_api import snapshot
from tests.imports.conftest import T1
from tests.my_account.test_api import add_post

PERIOD = 'from=2026-10-01&to=2026-10-03'


def url(c, query=PERIOD, route='overview'):
    return f'/api/v1/projects/{c.project_id}/dashboard/{route}?{query}'


def get(client, c, query=PERIOD):
    response = client.get(url(c, query))
    assert response.status_code == 200, response.text
    return response.json()


def followers(c, account_id=None, values=None):
    with c.factory() as s, s.begin():
        for day, value in values:
            s.add(AccountMetric(account_id=account_id or c.own_id, recorded_date=day, followers=value))


def insight(c, platform=None, day=1, content=None, project_id=None):
    with c.factory() as s, s.begin():
        row = AIInsight(project_id=project_id or c.project_id, platform=platform,
            analysis_from=date(2026, 9, 1), analysis_to=date(2026, 9, 30),
            created_at=T1 + timedelta(days=day), content=content if content is not None else {'summary': 'test'},
            model_name='fixture', prompt_version='test-v1')
        s.add(row); s.flush()
        return str(row.insight_id)


def test_empty_typed_contract(client, context):
    data = get(client, context)
    assert data['timezone'] == 'UTC'
    assert data['period'] == {'from': '2026-10-01', 'to': '2026-10-03'}
    assert data['previous_period'] == {'from': '2026-09-28', 'to': '2026-09-30'}
    assert data['kpis']['posts']['value'] == data['kpis']['posts']['change'] == 0
    assert data['kpis']['reach']['value'] is None
    assert data['top_trends'] == [] and data['top_opportunity'] is None and data['ai_summary'] is None
    assert data['competitor_aggregate']['account_count'] == 1
    assert data['performance_trend']['daily'] == [
        {'date': f'2026-10-0{i}', 'posts': 0, 'reach': None, 'engagement': None} for i in range(1, 4)]


@pytest.mark.parametrize('metrics,expected', [
    ({}, (None, None, None, None)),
    ({'reach': 0, 'likes': 0}, (0, None, 0, None)),
    ({'reach': 100, 'likes': 10}, (100, None, 10, 10)),
    ({'impressions': 200, 'comments': 4}, (None, 200, 4, 2)),
    ({'views': 400, 'shares': 8}, (None, None, 8, 2)),
    ({'reach': 100, 'impressions': 200, 'views': 400, 'saves': 3}, (100, 200, 3, 3)),
    ({'reach': 0, 'impressions': 200, 'likes': 2}, (0, 200, 2, None)),
    ({'reach': 100}, (100, None, None, None)),
    ({'reach': 100, 'likes': 0, 'comments': 3, 'shares': 2}, (100, None, 5, 5)),
])
def test_kpi_null_zero_and_denominators(client, context, metrics, expected):
    add_post(context, metrics=metrics)
    k = get(client, context)['kpis']
    assert tuple(k[key]['value'] for key in ('reach', 'impressions', 'engagement', 'engagement_rate')) == expected


def test_latest_metrics_daily_utc_and_own_only(client, context):
    add_post(context, posted_at=T1.replace(day=1, hour=0), snapshots=[{'reach': 999, 'likes': 999}, {'reach': 0, 'likes': 2}])
    add_post(context, posted_at=T1.replace(day=1, hour=23, minute=59, second=59), metrics={'reach': 3})
    add_post(context, posted_at=T1.replace(day=2), metrics={})
    add_post(context, source_type='COMPETITOR', account_id=context.competitor_id, metrics={'reach': 999})
    add_post(context, source_type='MARKET', account_id=None, metrics={'reach': 999})
    add_post(context, posted_at=T1.replace(day=1, hour=0) - timedelta(microseconds=1), metrics={'reach': 99})
    add_post(context, posted_at=T1.replace(day=4, hour=0), metrics={'reach': 99})
    data = get(client, context)
    assert (data['kpis']['posts']['value'], data['kpis']['reach']['value']) == (3, 3)
    assert data['performance_trend']['daily'] == [
        {'date': '2026-10-01', 'posts': 2, 'reach': 3, 'engagement': 2},
        {'date': '2026-10-02', 'posts': 1, 'reach': None, 'engagement': None},
        {'date': '2026-10-03', 'posts': 0, 'reach': None, 'engagement': None}]


@pytest.mark.parametrize('platform', ['ALL', 'X', 'INSTAGRAM'])
def test_cross_screen_kpi_opportunity_and_competitor(client, context, platform):
    own_ig, comp_ig = instagram(context)
    for acc, sns, role in [(context.own_id, 'X', 'OWN'), (own_ig, 'INSTAGRAM', 'OWN'),
                          (context.competitor_id, 'X', 'COMPETITOR'), (comp_ig, 'INSTAGRAM', 'COMPETITOR')]:
        match(context, add_post(context, account_id=acc, platform=sns, source_type=role, metrics={'reach': 100, 'likes': 3}))
        followers(context, acc, [(date(2026, 10, 2), 42)])
    for sns in ('X', 'INSTAGRAM'):
        snapshot(context, 80, platform=sns)
    q = PERIOD + '&platform=' + platform
    overview = get(client, context, q)
    own = client.get(f'/api/v1/projects/{context.project_id}/accounts/own/analytics?{q}').json()['kpis']
    for key in ('posts', 'reach', 'impressions', 'engagement', 'engagement_rate', 'followers'):
        assert overview['kpis'][key]['value'] == own[key]
    assert overview['kpis']['engagement_rate']['rate_groups'] == own['rate_groups']
    assert overview['kpis']['followers_by_account'] == own['followers_by_account']
    gap = client.get(f'/api/v1/projects/{context.project_id}/gap-analysis?{q}').json()['items']
    assert overview['top_opportunity'] == next(a for a in gap if a['gap_score'] is not None)
    assert overview['top_trends'][0]['trend_score'] == gap[0]['trend_score']
    ids = [context.competitor_id, comp_ig] if platform == 'ALL' else [context.competitor_id if platform == 'X' else comp_ig]
    comp = client.get(f'/api/v1/projects/{context.project_id}/competitors/analytics?{q}&account_ids={",".join(map(str, ids))}')
    assert comp.status_code == 200, comp.text
    rows = [a for a in comp.json()['accounts'] if a['role'] == 'COMPETITOR']
    assert sorted(overview['competitor_summary'], key=lambda a: a['account_id']) == sorted(rows, key=lambda a: a['account_id'])


def test_mixed_cohorts_not_averaged(client, context):
    own_ig, _ = instagram(context)
    add_post(context, metrics={'reach': 100, 'likes': 10})
    add_post(context, metrics={'impressions': 200, 'likes': 10})
    add_post(context, account_id=own_ig, platform='INSTAGRAM', metrics={'reach': 100, 'likes': 5})
    k = get(client, context)['kpis']
    assert k['engagement_rate']['value'] is None and len(k['engagement_rate']['rate_groups']) == 3
    assert k['engagement_rate']['change_point'] is None


@pytest.mark.parametrize('old,current,rate', [(None, 100, None), (0, 100, None), (100, 150, 50), (100, 0, -100)])
def test_previous_same_length_and_zero_base(client, context, old, current, rate):
    add_post(context, posted_at=T1.replace(month=9, day=30), metrics={'reach': old, 'likes': 2})
    add_post(context, metrics={'reach': current, 'likes': 4})
    k = get(client, context)['kpis']
    assert k['reach']['previous_value'] == old and k['reach']['change_rate'] == rate
    assert k['posts']['change'] == 0


def test_changed_denominator_not_compared_across_periods(client, context):
    add_post(context, posted_at=T1.replace(month=9, day=30), metrics={'views': 100, 'likes': 2})
    add_post(context, metrics={'reach': 100, 'likes': 4})
    k = get(client, context)['kpis']['engagement_rate']
    assert (k['value'], k['previous_value'], k['change_point']) == (4, 2, None)


def test_date_min_does_not_overflow_comparison(client, context):
    data = get(client, context, 'from=0001-01-01&to=0001-01-03')
    assert data['previous_period'] is None and data['kpis']['posts']['previous_value'] is None


@pytest.mark.parametrize('latest', [None, 0, 20])
def test_followers_latest_null_zero_future_and_no_carry(client, context, latest):
    followers(context, values=[(date(2026, 9, 30), 10), (date(2026, 10, 1), 15),
        (date(2026, 10, 3), latest), (date(2026, 10, 4), 999)])
    data = get(client, context)
    assert data['kpis']['followers']['value'] == latest
    assert data['kpis']['followers']['previous_value'] == 10
    assert data['performance_trend']['follower_series'][0]['values'] == [
        {'date': '2026-10-01', 'followers': 15, 'row_present': True},
        {'date': '2026-10-02', 'followers': None, 'row_present': False},
        {'date': '2026-10-03', 'followers': latest, 'row_present': True}]


def test_followers_all_non_additive_and_inactive_own_history(client, context):
    own_ig, _ = instagram(context)
    followers(context, values=[(date(2026, 10, 3), 50)])
    followers(context, own_ig, [(date(2026, 10, 3), 100)])
    data = get(client, context)
    assert data['kpis']['followers']['value'] is None
    assert len(data['kpis']['followers_by_account']) == len(data['performance_trend']['follower_series']) == 2
    add_post(context, metrics={'reach': 5})
    with context.factory() as s, s.begin():
        s.get(SNSAccount, context.own_id).is_active = False
    data = get(client, context)
    assert data['kpis']['posts']['value'] == 1 and data['kpis']['reach']['value'] == 5
    assert data['kpis']['followers']['value'] == 100
    assert len(data['performance_trend']['follower_series']) == 1


@pytest.mark.parametrize('score', [None, 0, 80])
def test_trend_latest_null_not_backfilled_term_excluded(client, context, score):
    snapshot(context, 99, date(2026, 10, 1))
    snapshot(context, score)
    snapshot(context, 100, date(2026, 10, 4))
    snapshot(context, 100, term_id=context.terms['ChatGPT'])
    data = get(client, context)
    assert data['top_trends'] == [] if score is None else data['top_trends'][0]['trend_score'] == score
    if score is not None:
        assert data['top_trends'][0]['trend_date'] == '2026-10-03'


def test_trend_top5_stable_sort_and_inactive(client, context):
    instagram(context)
    with context.factory() as s, s.begin():
        topics = [WatchTopic(project_id=context.project_id, topic_name=name, is_active=name != 'Disabled2')
                  for name in ['Z', 'A', 'B', 'C', 'D', 'E', 'Disabled2']]
        s.add_all(topics); s.flush()
        for topic in topics:
            for sns in ('X', 'INSTAGRAM'):
                s.add(TrendDaily(topic_id=topic.topic_id, platform=sns, trend_date=date(2026, 10, 3),
                    trend_score=99 if not topic.is_active else 80, post_growth_rate=-2))
    rows = get(client, context)['top_trends']
    assert [(r['topic_name'], r['platform']) for r in rows] == [('A', 'INSTAGRAM'), ('A', 'X'), ('B', 'INSTAGRAM'), ('B', 'X'), ('C', 'INSTAGRAM')]
    assert all(r['trend_direction'] == 'DOWN' for r in rows)


def test_competitor_post_weighted_and_active_only(client, context):
    other = account(context); inactive = account(context, active=False)
    add_post(context, account_id=context.competitor_id, source_type='COMPETITOR', metrics={'reach': 100, 'likes': 100})
    for _ in range(9):
        add_post(context, account_id=other, source_type='COMPETITOR', metrics={'impressions': 100, 'likes': 10})
    add_post(context, account_id=inactive, source_type='COMPETITOR', metrics={'likes': 999})
    add_post(context, source_type='MARKET', account_id=None, metrics={'likes': 999})
    value = get(client, context)['competitor_aggregate']
    assert (value['posts'], value['avg_engagement'], value['account_count']) == (10, 19, 2)
    assert value['avg_engagement_rate'] is None and len(value['rate_groups']) == 2


def test_competitor_top3_stable_name_order(client, context):
    ids = [account(context) for _ in range(5)]
    with context.factory() as s, s.begin():
        for i, acc in enumerate(ids):
            s.get(SNSAccount, acc).account_name = f'Account {i}'
    rows = get(client, context)['competitor_summary']
    assert [r['account_name'] for r in rows] == ['Account 0', 'Account 1', 'Account 2']
    assert get(client, context)['competitor_aggregate']['account_count'] == 6


@pytest.mark.parametrize('score,matched,classification', [(0, False, 'LOW_PRIORITY'), (80, False, 'OPPORTUNITY'), (80, True, 'BALANCED'), (20, True, 'HIGH_COVERAGE')])
def test_opportunity_zero_and_classification(client, context, score, matched, classification):
    post = add_post(context)
    if matched: match(context, post)
    snapshot(context, score)
    item = get(client, context)['top_opportunity']
    assert item['gap_score'] == (0 if matched else score) and item['classification'] == classification


@pytest.mark.parametrize('mode', ['no_topic', 'no_trend', 'no_own'])
def test_opportunity_missing_is_normal(client, context, mode):
    if mode != 'no_own': add_post(context)
    if mode != 'no_trend': snapshot(context)
    if mode == 'no_topic':
        with context.factory() as s, s.begin(): s.get(WatchTopic, context.topic_id).is_active = False
    assert get(client, context)['top_opportunity'] is None


@pytest.mark.parametrize('platform', ['ALL', 'X', 'INSTAGRAM'])
def test_ai_platform_preference_then_latest(client, context, platform):
    instagram(context)
    all_id = insight(context, day=0)
    x_id = insight(context, 'X', day=3)
    ig_id = insight(context, 'INSTAGRAM', day=2)
    assert get(client, context, PERIOD + '&platform=' + platform)['ai_summary']['insight_id'] == {
        'ALL': all_id, 'X': x_id, 'INSTAGRAM': ig_id}[platform]


@pytest.mark.parametrize('content', [{'summary': 'saved'}, {'summary': 0}, ['unknown', {'x': 1}], {'future': {'nested': [None, 0]}}])
def test_ai_content_retained_latest_and_metadata(client, context, content):
    insight(context, day=0)
    expected = insight(context, day=1, content=content)
    row = get(client, context)['ai_summary']
    assert row['insight_id'] == expected and row['content'] == content
    assert row['model_name'] == 'fixture' and row['prompt_version'] == 'test-v1'
    assert row['analysis_from'] == '2026-09-01'


def test_ai_fallback_enabled_scope(client, context):
    insight(context, 'INSTAGRAM', day=9)
    expected = insight(context, 'X')
    assert get(client, context)['ai_summary']['insight_id'] == expected
    # For a specific SNS, ALL is an eligible fallback, other SNS is not.
    with context.factory() as s, s.begin(): s.execute(delete(AIInsight).where(AIInsight.project_id == context.project_id))
    expected = insight(context)
    assert get(client, context, PERIOD + '&platform=X')['ai_summary']['insight_id'] == expected


def test_project_isolation_every_section(client, context):
    with context.factory() as s, s.begin():
        foreign = Project(name='isolated overview'); s.add(foreign); s.flush()
        foreign_id = foreign.project_id
        topic = WatchTopic(project_id=foreign_id, topic_name='foreign'); s.add(topic); s.flush()
        s.add(TrendDaily(topic_id=topic.topic_id, platform='X', trend_date=date(2026, 10, 3), trend_score=99))
        acc = SNSAccount(project_id=foreign_id, platform='X', account_role='COMPETITOR', account_name='foreign')
        s.add(acc); s.flush(); acc_id = acc.account_id
    try:
        add_post(context, project_id=foreign_id, account_id=acc_id, source_type='COMPETITOR', metrics={'reach': 999, 'likes': 999})
        add_post(context, project_id=foreign_id, metrics={'reach': 999})
        insight(context, project_id=foreign_id)
        data = get(client, context)
        assert data['kpis']['posts']['value'] == data['competitor_aggregate']['posts'] == 0
        assert data['top_trends'] == [] and data['ai_summary'] is None and data['top_opportunity'] is None
    finally:
        with context.factory() as s, s.begin(): s.execute(delete(Project).where(Project.project_id == foreign_id))


@pytest.mark.parametrize('query,status', [
    ('to=2026-10-03', 422), ('from=2026-10-01', 422), ('from=bad&to=2026-10-03', 422),
    ('from=2026-10-01&to=bad', 422), ('from=2026-10-04&to=2026-10-03', 400),
    ('from=2000-01-01&to=2026-10-03', 400), (PERIOD + '&platform=TIKTOK', 422),
    (PERIOD + '&platform=INSTAGRAM', 404), (PERIOD + '&platform=SELECT secret', 422),
    ('from=DROP TABLE posts&to=2026-10-03', 422)])
def test_validation(client, context, query, status):
    result = client.get(url(context, query))
    assert result.status_code == status and 'error' in result.json()
    assert 'SELECT secret' not in result.text and 'DROP TABLE' not in result.text


@pytest.mark.parametrize('project,status', [('bad-uuid', 422), (str(uuid4()), 404)])
def test_project_validation(client, context, project, status):
    assert client.get(url(context).replace(str(context.project_id), project)).status_code == status


def test_period_limit_3660_inclusive(client, context):
    start = date(2026, 10, 3) - timedelta(days=3659)
    assert client.get(url(context, f'from={start}&to=2026-10-03')).status_code == 200
    assert client.get(url(context, f'from={start-timedelta(days=1)}&to=2026-10-03')).status_code == 400


def test_safe_internal_error(client, context, monkeypatch):
    def broken(*args): raise RuntimeError('password secret SQL')
    monkeypatch.setattr(OverviewRepository, 'insight', broken)
    result = client.get(url(context))
    assert result.status_code == 500 and result.json()['error']['code'] == 'ANALYTICS_ERROR'
    assert 'secret' not in result.text


@pytest.mark.parametrize('metric', ['reach', 'engagement', 'posts', 'followers'])
def test_performance_endpoint_matches_embedded_series(client, context, metric):
    add_post(context, metrics={'reach': 10, 'likes': 0})
    followers(context, values=[(date(2026, 10, 3), 0)])
    embedded = get(client, context)['performance_trend']
    result = client.get(url(context, PERIOD + '&metric=' + metric, 'performance-trend'))
    assert result.status_code == 200, result.text
    value = result.json()
    assert value['metric'] == metric
    if metric == 'followers':
        assert value['series'] == [] and value['follower_series'] == embedded['follower_series']
    else:
        assert value['series'] == [{'date': d['date'], 'value': d[metric]} for d in embedded['daily']]


def test_one_snapshot_despite_concurrent_writer(client, context, monkeypatch):
    post = add_post(context, metrics={'reach': 10, 'likes': 1})
    snapshot(context, 80)
    original = OverviewRepository.accounts
    def concurrent(s, project_id, platforms):
        with context.factory() as writer, writer.begin():
            writer.add(PostMetric(post_id=post, recorded_at=T1 + timedelta(hours=1), reach=999, likes=999))
            writer.add(TrendDaily(topic_id=context.topic_id, platform='X', trend_date=date(2026, 10, 2), trend_score=99))
            writer.execute(text('UPDATE trend_daily SET trend_score=10 WHERE topic_id=:id AND trend_date=:day'),
                           {'id': context.topic_id, 'day': date(2026, 10, 3)})
            writer.add(AIInsight(project_id=context.project_id, analysis_from=date(2026, 10, 1),
                analysis_to=date(2026, 10, 3), content={'summary': 'concurrent'}))
        return original(s, project_id, platforms)
    monkeypatch.setattr(OverviewRepository, 'accounts', staticmethod(concurrent))
    data = get(client, context)
    assert data['kpis']['reach']['value'] == 10
    assert data['own_summary']['avg_engagement'] == 1
    assert data['top_trends'][0]['trend_score'] == data['top_opportunity']['trend_score'] == 80
    assert data['ai_summary'] is None


def test_read_only_single_connection_and_fixed_queries_large_dataset(context, postgres_engine, monkeypatch):
    own_ig, comp_ig = instagram(context)
    filters = MyAccountService.filters(date(2026, 10, 1), date(2026, 10, 3))
    service = OverviewService(context.factory)
    statements, connections, modes = [], set(), []
    original = OverviewRepository.insight
    def verify_mode(s, *args):
        modes.append((s.scalar(text('SHOW transaction_read_only')), s.scalar(text('SHOW transaction_isolation'))))
        return original(s, *args)
    monkeypatch.setattr(OverviewRepository, 'insight', staticmethod(verify_mode))
    def record(conn, cursor, statement, *args):
        statements.append(statement); connections.add(id(conn))
    def measured():
        statements.clear(); connections.clear()
        event.listen(postgres_engine, 'before_cursor_execute', record)
        try: data = service.overview(context.project_id, filters)
        finally: event.remove(postgres_engine, 'before_cursor_execute', record)
        assert len(connections) == 1
        assert modes[-1] == ('on', 'repeatable read')
        assert not any(s.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'COMMIT')) for s in statements)
        return data, sum(s.lstrip().upper().startswith(('SELECT', 'WITH')) for s in statements)
    small, small_count = measured()
    extra = [account(context) for _ in range(5)]
    with context.factory() as s, s.begin():
        topics = [WatchTopic(project_id=context.project_id, topic_name=f'Scale{i:03}') for i in range(99)]
        s.add_all(topics); s.flush(); topic_ids = [context.topic_id] + [a.topic_id for a in topics]
        posts, metrics, matches = [], [], []
        for i in range(2000):
            sns = 'X' if i % 2 == 0 else 'INSTAGRAM'
            own = i < 1000
            acc = (context.own_id if sns == 'X' else own_ig) if own else (extra[i % 5] if sns == 'X' else comp_ig)
            post_id = uuid4()
            posts.append(dict(post_id=post_id, project_id=context.project_id, account_id=acc,
                source_type='OWN' if own else 'COMPETITOR', platform=sns, platform_post_id=str(i), posted_at=T1))
            metrics.append(dict(post_id=post_id, recorded_at=T1, reach=10, likes=i % 7))
            matches.append(dict(post_id=post_id, topic_id=topic_ids[i % 100], match_type='MANUAL'))
        s.execute(insert(SNSPost), posts); s.execute(insert(PostMetric), metrics); s.execute(insert(PostTopic), matches)
        for tid in topic_ids:
            for sns in ('X', 'INSTAGRAM'):
                s.add(TrendDaily(topic_id=tid, platform=sns, trend_date=date(2026, 10, 3), trend_score=80))
        for acc in [context.own_id, own_ig, context.competitor_id, comp_ig] + extra:
            for day in range(1, 4): s.add(AccountMetric(account_id=acc, recorded_date=date(2026, 10, day), followers=day))
        for day in range(4): s.add(AIInsight(project_id=context.project_id, analysis_from=filters.start,
            analysis_to=filters.end, created_at=T1 + timedelta(days=day), content={'summary': 'scale'}))
    large, large_count = measured()
    assert small_count == large_count == 16
    assert large.kpis.posts.value == 1000 and large.competitor_aggregate.posts == 1000
    assert large.kpis.reach.value == 10000
    assert len(large.top_trends) == 5 and len(large.competitor_summary) == 3
    assert len(large.performance_trend.follower_series) == 2
    assert large.ai_summary.content == {'summary': 'scale'}
