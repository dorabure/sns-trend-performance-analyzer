from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, insert, select, text

from app.db.models import AccountMetric, PostMetric, PostTopic, Project, ProjectPlatform, SNSAccount, SNSPost, WatchTopic
from app.repositories.competitor_repository import CompetitorRepository
from app.services.competitor_service import CompetitorService
from tests.imports.conftest import T1
from tests.my_account.test_api import add_post

ROUTES = ('analytics', 'topic-distribution', 'top-posts')
PERIOD = 'from=2026-10-01&to=2026-10-03'


def url(c, route, query=None, ids=None):
    selected = ','.join(str(i) for i in (ids if ids is not None else [c.competitor_id]))
    return f'/api/v1/projects/{c.project_id}/competitors/{route}?{query or PERIOD}&account_ids={selected}'


def get(client, c, route='analytics', **kw):
    r = client.get(url(c, route, **kw))
    assert r.status_code == 200, r.text
    return r.json()


def competitor(c, **kw):
    return add_post(c, **{'account_id': c.competitor_id, 'source_type': 'COMPETITOR', **kw})


def row(response, account_id):
    return next(a for a in response['accounts'] if a['account_id'] == str(account_id))


def account(c, platform='X', role='COMPETITOR', active=True):
    with c.factory() as s, s.begin():
        a = SNSAccount(project_id=c.project_id, platform=platform, account_name=str(uuid4()),
                       display_name='比較 Account', account_role=role, is_active=active)
        s.add(a); s.flush()
        return a.account_id


def instagram(c):
    with c.factory() as s, s.begin():
        s.add(ProjectPlatform(project_id=c.project_id, platform='INSTAGRAM'))
    return account(c, 'INSTAGRAM', 'OWN'), account(c, 'INSTAGRAM')


def match(c, post_id, topic_id=None, kind='KEYWORD'):
    with c.factory() as s, s.begin():
        s.add(PostTopic(post_id=post_id, topic_id=topic_id or c.topic_id, match_type=kind))


def test_empty_contract(client, context):
    a = get(client, context)
    assert a['timezone'] == 'UTC' and a['posting_frequency_unit'] == 'posts/day'
    assert {x['role'] for x in a['accounts']} == {'OWN', 'COMPETITOR'}
    for x in a['accounts']:
        assert x['posts'] == x['posting_frequency'] == 0
        assert all(x[k] is None for k in ('followers', 'followers_as_of', 'avg_views', 'avg_likes',
                                         'avg_comments', 'avg_shares', 'avg_engagement', 'avg_engagement_rate'))
        assert x['engagement_rate_groups'] == []
    d = get(client, context, 'topic-distribution')
    assert len(d['topics']) == 1 and d['overlapping_topics'] is True
    assert all(x['total_posts'] == x['matched_posts'] == 0 and x['ratio'] is None for x in d['topics'][0]['accounts'])
    assert get(client, context, 'top-posts')['items'] == []


def test_latest_known_averages_and_frequency(client, context):
    competitor(context, snapshots=[{'views': 999, 'likes': 99}, {'views': 100, 'likes': 10, 'comments': 2}])
    competitor(context, snapshots=[{'views': 500, 'likes': 50}, {'views': None, 'likes': None}])
    competitor(context, metrics={'views': 0, 'likes': 0, 'comments': 0, 'shares': 0})
    a = row(get(client, context), context.competitor_id)
    assert (a['posts'], a['posting_frequency'], a['avg_views'], a['avg_likes']) == (3, 1, 50, 5)
    assert a['avg_comments'] == 1 and a['avg_shares'] == 0 and a['avg_engagement'] == 6
    items = get(client, context, 'top-posts')['items']
    assert [i['engagement'] for i in items] == [12, 0, None]
    assert items[2]['views'] is None and items[2]['recorded_at'] is not None
    assert items[0]['account_id'] == str(context.competitor_id) and 'display_name' in items[0]


@pytest.mark.parametrize('metrics,rate,kind', [
    ({'reach': 100, 'impressions': 200, 'views': 300}, 10, 'reach'),
    ({'impressions': 200, 'views': 300}, 5, 'impressions'),
    ({'views': 200}, 5, 'views'), ({'reach': 0, 'impressions': 100}, None, 'reach'),
    ({'impressions': 0, 'views': 100}, None, 'impressions'), ({'views': 0}, None, 'views'), ({}, None, None),
])
def test_er_first_nonnull_denominator(client, context, metrics, rate, kind):
    competitor(context, metrics={'likes': 10, **metrics})
    a = row(get(client, context), context.competitor_id)
    p = get(client, context, 'top-posts')['items'][0]
    assert a['avg_engagement_rate'] == rate and p['engagement_rate'] == rate and p['denominator_type'] == kind


def test_mixed_er_groups_never_scalar_average(client, context):
    competitor(context, metrics={'reach': 100, 'likes': 10})
    competitor(context, metrics={'views': 200, 'likes': 10})
    add_post(context, metrics={'impressions': 100, 'likes': 20})
    a = get(client, context)
    comp = row(a, context.competitor_id)
    assert comp['avg_engagement_rate'] is None
    assert {(g['platform'], g['denominator_type'], g['avg_engagement_rate']) for g in comp['engagement_rate_groups']} == {('X', 'reach', 10), ('X', 'views', 5)}
    assert row(a, context.own_id)['avg_engagement_rate'] == 20


@pytest.mark.parametrize('value', [None, 0, 42])
def test_followers_latest_as_of_no_future_or_backfill(client, context, value):
    with context.factory() as s, s.begin():
        for day, followers in [(date(2026, 9, 1), 999), (date(2026, 10, 3), value), (date(2026, 10, 4), 888)]:
            s.add(AccountMetric(account_id=context.competitor_id, recorded_date=day, followers=followers))
    a = row(get(client, context), context.competitor_id)
    assert a['followers'] == value and a['followers_as_of'] == '2026-10-03'
    before = row(get(client, context, query='from=2026-10-01&to=2026-10-02'), context.competitor_id)
    assert before['followers'] == 999 and before['followers_as_of'] == '2026-09-01'


def test_all_keeps_two_own_and_three_competitors_separate(client, context):
    own_ig, comp_ig = instagram(context)
    comp_x = account(context)
    ids = [context.competitor_id, comp_ig, comp_x]
    for a, platform, role in [(context.own_id, 'X', 'OWN'), (own_ig, 'INSTAGRAM', 'OWN'),
                              (context.competitor_id, 'X', 'COMPETITOR'), (comp_ig, 'INSTAGRAM', 'COMPETITOR'), (comp_x, 'X', 'COMPETITOR')]:
        add_post(context, account_id=a, platform=platform, source_type=role, metrics={'views': 100, 'likes': 5})
    result = get(client, context, ids=ids)
    assert len(result['accounts']) == 5 and all(x['posts'] == 1 for x in result['accounts'])
    assert len(get(client, context, 'top-posts', ids=ids)['items']) == 3
    ig = get(client, context, query=PERIOD+'&platform=INSTAGRAM', ids=[comp_ig])
    assert {x['account_id'] for x in ig['accounts']} == {str(own_ig), str(comp_ig)}


@pytest.mark.parametrize('route', ROUTES)
@pytest.mark.parametrize('selection', ['empty', 'duplicate', 'four', 'malformed', 'own', 'missing', 'inactive', 'wrong_platform', 'disabled_platform'])
def test_selection_errors(client, context, route, selection):
    ids = [context.competitor_id]
    expected = 404
    if selection == 'empty': ids, expected = [], 400
    elif selection == 'duplicate': ids, expected = ids*2, 400
    elif selection == 'four': ids, expected = [uuid4() for _ in range(4)], 400
    elif selection == 'malformed': ids, expected = ['SELECT secret FROM private'], 422
    elif selection == 'own': ids = [context.own_id]
    elif selection == 'missing': ids = [uuid4()]
    elif selection == 'inactive': ids = [account(context, active=False)]
    elif selection == 'wrong_platform':
        _, ig = instagram(context); ids = [ig]
    elif selection == 'disabled_platform': ids = [account(context, 'INSTAGRAM')]
    query = PERIOD+'&platform=X' if selection == 'wrong_platform' else PERIOD
    r = client.get(url(context, route, query=query, ids=ids))
    assert r.status_code == expected, r.text
    assert 'SELECT secret' not in r.text


@pytest.mark.parametrize('route', ROUTES)
@pytest.mark.parametrize('query,status', [('from=2026-10-04&to=2026-10-03',400),
    ('from=2000-01-01&to=2026-10-03',400), ('from=bad&to=2026-10-03',422), (PERIOD+'&platform=TIKTOK',422)])
def test_period_platform_validation(client, context, route, query, status):
    assert client.get(url(context, route, query=query)).status_code == status


@pytest.mark.parametrize('route', ROUTES)
def test_missing_selection_and_unknown_project(client, context, route):
    assert client.get(f'/api/v1/projects/{context.project_id}/competitors/{route}?{PERIOD}').status_code == 422
    assert client.get(url(context, route).replace(str(context.project_id), str(uuid4()))).status_code == 404


def test_cross_project_and_corrupt_post_integrity(client, context):
    with context.factory() as s, s.begin():
        foreign = Project(name='Foreign isolated competitor'); s.add(foreign); s.flush()
        other = SNSAccount(project_id=foreign.project_id, platform='X', account_name='foreign', account_role='COMPETITOR')
        s.add(other); s.flush(); other_id, foreign_id = other.account_id, foreign.project_id
    try:
        for route in ROUTES:
            assert client.get(url(context, route, ids=[other_id])).status_code == 404
        valid = competitor(context, metrics={'likes': 1})
        for fields in [dict(source_type='OWN'), dict(platform='INSTAGRAM'), dict(project_id=foreign_id), dict(account_id=other_id)]:
            bad = competitor(context, metrics={'likes': 999}, **fields)
            match(context, bad)
        add_post(context, source_type='COMPETITOR', metrics={'likes': 999})
        add_post(context, source_type='MARKET', account_id=None, metrics={'likes': 999})
        match(context, valid)
        assert row(get(client, context), context.competitor_id)['posts'] == 1
        assert [i['post_id'] for i in get(client, context, 'top-posts')['items']] == [str(valid)]
        d = row(get(client, context, 'topic-distribution')['topics'][0], context.competitor_id)
        assert (d['matched_posts'], d['total_posts'], d['ratio']) == (1, 1, 100)
    finally:
        with context.factory() as s, s.begin(): s.execute(delete(Project).where(Project.project_id == foreign_id))


def test_inactive_own_not_automatically_added(client, context):
    add_post(context)
    with context.factory() as s, s.begin(): s.get(SNSAccount, context.own_id).is_active = False
    assert len(get(client, context)['accounts']) == 1


def test_utc_inclusive_boundaries(client, context):
    start = T1.replace(day=1, hour=0)
    end = T1.replace(day=3, hour=23, minute=59, second=59, microsecond=999999)
    for instant in [start-timedelta(microseconds=1), start, end, end+timedelta(microseconds=1)]:
        match(context, competitor(context, posted_at=instant, metrics={'likes': 1}))
    assert row(get(client, context), context.competitor_id)['posts'] == 2
    assert len(get(client, context, 'top-posts')['items']) == 2
    assert row(get(client, context, 'topic-distribution')['topics'][0], context.competitor_id)['matched_posts'] == 2


@pytest.mark.parametrize('kind', ['KEYWORD', 'HASHTAG', 'MANUAL', 'AI'])
def test_existing_matches_all_methods_no_rematch(client, context, kind):
    # Unmatched ChatGPT text must stay unmatched; arbitrary text with an existing relation counts.
    competitor(context)
    match(context, competitor(context, text='existing relation only'), kind=kind)
    d = row(get(client, context, 'topic-distribution')['topics'][0], context.competitor_id)
    assert (d['matched_posts'], d['total_posts'], d['ratio']) == (1, 2, 50)


def test_overlapping_topics_active_only_and_zero_ratio(client, context):
    with context.factory() as s, s.begin():
        active = WatchTopic(project_id=context.project_id, topic_name='Overlap')
        empty = WatchTopic(project_id=context.project_id, topic_name='Unmatched')
        inactive = s.scalar(select(WatchTopic).where(WatchTopic.project_id==context.project_id, WatchTopic.is_active.is_(False)))
        s.add_all([active, empty]); s.flush(); active_id, inactive_id = active.topic_id, inactive.topic_id
    p = competitor(context); match(context, p); match(context, p, active_id); match(context, p, inactive_id)
    d = get(client, context, 'topic-distribution')
    assert len(d['topics']) == 3
    ratios = [row(t, context.competitor_id)['ratio'] for t in d['topics']]
    assert sorted(ratios) == [0, 100, 100] and sum(ratios) == 200
    assert all(row(t, context.own_id)['ratio'] is None for t in d['topics'])


def test_top_order_latest_null_last_ties_and_limits(client, context):
    ids = [competitor(context, snapshots=[{'likes': 999}, {'likes': 5}], posted_at=T1) for _ in range(2)]
    newer = competitor(context, metrics={'likes': 5}, posted_at=T1+timedelta(hours=1))
    zero = competitor(context, metrics={'likes': 0})
    missing = competitor(context)
    add_post(context, metrics={'likes': 9999})
    other = account(context); add_post(context, account_id=other, source_type='COMPETITOR', metrics={'likes': 9999})
    items = get(client, context, 'top-posts')['items']
    assert [p['post_id'] for p in items] == [str(newer), *sorted(map(str, ids)), str(zero), str(missing)]
    for _ in range(12): competitor(context, metrics={'likes': 1})
    assert len(get(client, context, 'top-posts')['items']) == 10
    assert len(get(client, context, 'top-posts', query=PERIOD+'&limit=50')['items']) == 17
    assert len(get(client, context, 'top-posts', query=PERIOD+'&limit=1')['items']) == 1
    for limit in (0,51): assert client.get(url(context, 'top-posts', query=PERIOD+f'&limit={limit}')).status_code == 422


@pytest.mark.parametrize('route,max_queries', [('analytics',5), ('topic-distribution',5), ('top-posts',4)])
def test_thousand_posts_fixed_queries_and_readonly(context, route, max_queries):
    selected = [context.competitor_id, account(context), account(context)]
    with context.factory() as s, s.begin():
        topic = WatchTopic(project_id=context.project_id, topic_name='Second'); s.add(topic); s.flush()
        post_ids = [uuid4() for _ in range(1000)]
        s.execute(insert(SNSPost), [dict(post_id=p, project_id=context.project_id, account_id=selected[i%3],
            source_type='COMPETITOR', platform='X', platform_post_id=str(p), posted_at=T1, text='bulk', raw_data={}) for i,p in enumerate(post_ids)])
        s.execute(insert(PostMetric), [dict(post_id=p, recorded_at=T1, views=100, likes=1, raw_metrics={}) for p in post_ids])
        s.execute(insert(PostTopic), [dict(post_id=p, topic_id=t, match_type='AI') for p in post_ids for t in [context.topic_id, topic.topic_id]])
    service = CompetitorService(context.factory)
    engine = context.factory.kw['bind']
    statements, modes = [], []
    def capture(conn, cursor, statement, params, ctx, many):
        statements.append(statement.strip().split()[0].upper())
    # Verify the actual service transaction before repository access, without changing its mode.
    original_accounts = service.repository.accounts
    def checked_accounts(s, *args):
        modes.append((s.scalar(text('SHOW transaction_read_only')), s.scalar(text('SHOW transaction_isolation'))))
        return original_accounts(s, *args)
    service.repository.accounts = checked_accounts
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        filters = service.filters(date(2026,10,1), date(2026,10,3), 'ALL')
        result = getattr(service, route.replace('-','_'))(context.project_id, selected, filters, *([50] if route=='top-posts' else []))
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    assert modes == [('on', 'repeatable read')]
    assert not {'INSERT','UPDATE','DELETE','COMMIT'} & set(statements)
    assert sum(x in ('SELECT','WITH') for x in statements) <= max_queries
    if route == 'analytics': assert sum(a.posts for a in result.accounts) == 1000
    elif route == 'top-posts': assert len(result.items) == 50
    else:
        assert len(result.topics) == 2
        assert all(a.ratio == 100 for t in result.topics for a in t.accounts if a.role == 'COMPETITOR')


@pytest.mark.parametrize('route', ROUTES)
def test_generic_errors_hide_internal_details(client, context, monkeypatch, route):
    def broken(*args): raise RuntimeError('postgres password=secret SELECT sensitive_data')
    monkeypatch.setattr(CompetitorRepository, 'accounts', broken)
    r = client.get(url(context, route))
    assert r.status_code == 500 and r.json()['error']['code'] == 'ANALYTICS_ERROR'
    assert 'secret' not in r.text and 'sensitive' not in r.text


def test_missing_metric_zero_engagement_and_unweighted_rate(client, context):
    competitor(context)
    competitor(context, metrics={'reach': 100, 'likes': 0})
    competitor(context, metrics={'reach': 1000, 'likes': 100})
    a = row(get(client, context), context.competitor_id)
    assert a['posts'] == 3 and a['avg_engagement'] == 50 and a['avg_engagement_rate'] == 5
    assert a['avg_views'] is None and a['avg_comments'] is None and a['avg_shares'] is None
    assert a['engagement_rate_groups'][0]['post_count'] == 2


@pytest.mark.parametrize('route', ROUTES)
def test_max_inclusive_period_allowed(client, context, route):
    start = date(2026,10,3)-timedelta(days=3659)
    assert client.get(url(context, route, query=f'from={start}&to=2026-10-03')).status_code == 200


def test_foreign_topic_relation_excluded(client, context):
    with context.factory() as s, s.begin():
        project = Project(name='Foreign Topic'); s.add(project); s.flush()
        topic = WatchTopic(project_id=project.project_id, topic_name='Hidden'); s.add(topic); s.flush()
        project_id, topic_id = project.project_id, topic.topic_id
    try:
        match(context, competitor(context), topic_id)
        d = get(client, context, 'topic-distribution')
        assert [t['topic_name'] for t in d['topics']] == ['AI']
        assert row(d['topics'][0], context.competitor_id)['ratio'] == 0
    finally:
        with context.factory() as s, s.begin(): s.execute(delete(Project).where(Project.project_id==project_id))
