from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event, func, select

from app.db.models import AccountMetric, PostMetric, PostTopic, Project, ProjectPlatform, SNSAccount, SNSPost, WatchTopic
from app.services.my_account_service import MyAccountService
from tests.imports.conftest import T1

START = date(2026, 10, 1)
END = date(2026, 10, 3)
QUERY = "from=2026-10-01&to=2026-10-03"


def base(context): return f"/api/v1/projects/{context.project_id}"


def add_post(context, *, metrics=None, snapshots=None, **fields):
    with context.factory() as s, s.begin():
        p = SNSPost(project_id=context.project_id, account_id=context.own_id, source_type="OWN", platform="X",
                    platform_post_id=str(uuid4()), posted_at=T1, text="ChatGPT活用", media_type="TEXT", hashtags=["#生成AI"], raw_data={})
        for key, value in fields.items(): setattr(p, key, value)
        s.add(p); s.flush(); post_id = p.post_id
        if metrics is not None:
            s.add(PostMetric(post_id=post_id, recorded_at=T1, raw_metrics={}, **metrics))
        for offset, values in enumerate(snapshots or []):
            s.add(PostMetric(post_id=post_id, recorded_at=T1 + timedelta(hours=offset), raw_metrics={}, **values))
    return post_id


def analytics(client, context, query=QUERY):
    r = client.get(base(context) + '/accounts/own/analytics?' + query)
    assert r.status_code == 200, r.text
    return r.json()


def posts(client, context, query=QUERY):
    r = client.get(base(context) + '/accounts/own/posts?' + query)
    assert r.status_code == 200, r.text
    return r.json()


def detail(client, context, post_id, query=QUERY):
    r = client.get(base(context) + f'/posts/{post_id}?' + query)
    assert r.status_code == 200, r.text
    return r.json()


def test_empty_contract(client, context):
    a = analytics(client, context)
    assert a["kpis"]["posts"] == 0
    for key in ("reach", "impressions", "engagement", "engagement_rate", "followers", "avg_engagement"):
        assert a["kpis"][key] is None
    assert len(a["engagement_trend"]) == 3 and all(d["post_count"] == 0 and d["engagement_total"] is None for d in a["engagement_trend"])
    assert a["media_type_performance"] == []
    assert posts(client, context) == {"items": [], "total": 0, "page": 1, "page_size": 20}


def test_own_scope_and_inactive_history(client, context):
    own = add_post(context, metrics={"reach": 100, "likes": 10})
    add_post(context, source_type="COMPETITOR", account_id=context.competitor_id, metrics={"reach": 900, "likes": 900})
    market = add_post(context, source_type="MARKET", account_id=None, metrics={"reach": 900, "likes": 900})
    with context.factory() as s, s.begin():
        s.get(SNSAccount, context.own_id).is_active = False
        s.get(Project, context.project_id).is_active = False
    a = analytics(client, context)
    assert a["kpis"]["posts"] == 1 and a["kpis"]["reach"] == 100
    assert posts(client, context)["items"][0]["post_id"] == str(own)
    assert client.get(base(context) + f"/posts/{market}").status_code == 404
    assert detail(client, context, own)["metrics"]["engagement"] == 10


def test_latest_metric_never_sums_snapshots(client, context):
    p = add_post(context, snapshots=[{"reach": 1000, "likes": 100}, {"reach": 50, "likes": 0, "comments": 2}])
    m = detail(client, context, p)["metrics"]
    assert m["reach"] == 50 and m["likes"] == 0 and m["engagement"] == 2 and m["engagement_rate"] == 4
    assert datetime.fromisoformat(m["recorded_at"]) == T1 + timedelta(hours=1)
    a = analytics(client, context)
    assert (a["kpis"]["reach"], a["kpis"]["engagement"]) == (50, 2)
    assert posts(client, context)["items"][0]["reach"] == 50


@pytest.mark.parametrize("values,expected", [({}, None), ({"likes": 10, "comments": None, "shares": 3, "saves": None}, 13), ({"likes": 0, "comments": 0, "shares": 0, "saves": 0}, 0)])
def test_engagement_null_zero(client, context, values, expected):
    p = add_post(context, metrics={"reach": 100, **values})
    a = analytics(client, context)
    assert a["kpis"]["engagement"] == expected and a["kpis"]["avg_engagement"] == expected
    assert detail(client, context, p)["metrics"]["engagement"] == expected


def test_missing_metric_preserves_post(client, context):
    p = add_post(context, media_type=None)
    d = detail(client, context, p)
    assert d["metrics"]["recorded_at"] is None and d["metrics"]["engagement"] is None
    assert d["comparison"]["rank"] is None
    assert posts(client, context)["total"] == 1
    a = analytics(client, context)
    assert a["media_type_performance"][0]["media_type"] is None


@pytest.mark.parametrize("values,rate,kind", [({"reach": 100, "impressions": 200, "views": 300}, 10, "reach"), ({"reach": None, "impressions": 200}, 5, "impressions"), ({"views": 200}, 5, "views"), ({"reach": 0, "impressions": 100}, None, "reach"), ({}, None, None)])
def test_rate_in_response(client, context, values, rate, kind):
    p = add_post(context, metrics={"likes": 10, **values})
    m = detail(client, context, p)["metrics"]
    assert m["engagement_rate"] == rate and m["denominator_type"] == kind


def test_kpi_average_only_known_rates(client, context):
    add_post(context, metrics={"reach": 100, "likes": 10})
    add_post(context, metrics={"reach": 100, "likes": 0})
    add_post(context, metrics={"reach": 100})
    add_post(context)
    k = analytics(client, context)["kpis"]
    assert (k["posts"], k["engagement"], k["avg_engagement"], k["engagement_rate"], k["reach"]) == (4, 10, 5, 5, 300)
    assert k["rate_groups"][0]["post_count"] == 2


def test_mixed_denominators_not_averaged(client, context):
    add_post(context, metrics={"reach": 100, "likes": 10})
    add_post(context, metrics={"views": 10, "likes": 10})
    a = analytics(client, context)
    assert a["kpis"]["engagement_rate"] is None and len(a["kpis"]["rate_groups"]) == 2
    assert a["media_type_performance"][0]["avg_engagement_rate"] is None


def test_platform_enabled_filters_and_multi_platform_cohorts(client, context):
    add_post(context, metrics={"reach": 100, "likes": 10})
    add_post(context, platform="INSTAGRAM", account_id=None, metrics={"reach": 100, "likes": 20})
    assert analytics(client, context)["kpis"]["posts"] == 1
    assert analytics(client, context, QUERY + "&platform=INSTAGRAM")["kpis"]["posts"] == 0
    with context.factory() as s, s.begin(): s.add(ProjectPlatform(project_id=context.project_id, platform="INSTAGRAM"))
    assert analytics(client, context, QUERY + "&platform=ALL")["kpis"]["posts"] == 2
    assert analytics(client, context)["kpis"]["engagement_rate"] is None
    assert analytics(client, context, QUERY + "&platform=X")["kpis"]["engagement"] == 10
    assert posts(client, context, QUERY + "&platform=INSTAGRAM")["total"] == 1


@pytest.mark.parametrize("time,included", [("2026-09-30T23:59:59.999999+00:00", False), ("2026-10-01T00:00:00+00:00", True), ("2026-10-03T23:59:59.999999+00:00", True), ("2026-10-04T00:00:00+00:00", False), ("2026-10-01T00:00:00+09:00", False), ("2026-10-01T09:00:00+09:00", True)])
def test_period_utc_boundaries(client, context, time, included):
    add_post(context, posted_at=datetime.fromisoformat(time), metrics={"likes": 1})
    assert analytics(client, context)["kpis"]["posts"] == int(included)
    assert posts(client, context)["total"] == int(included)


@pytest.mark.parametrize("query,expected", [("keyword=chatgpt", 1), ("keyword=ＣＨＡＴＧＰＴ", 1), ("keyword=CHATGPT", 1), ("keyword=生成ai", 1), ("keyword=100%25", 1), ("keyword=_", 1), ("keyword=nonexistent", 0), ("keyword=", 1), ("hashtag=生成AI", 1), ("hashtag=%23生成ai", 1), ("hashtag=生成", 0), ("hashtag=missing", 0)])
def test_normalized_search_and_literal_wildcards(client, context, query, expected):
    p = add_post(context, text="ＣｈａｔＧＰＴ 生成ＡＩ 100% _", hashtags=["#生成AI"], metrics={"likes": 1})
    before = detail(client, context, p)["post"]
    assert analytics(client, context, QUERY + '&' + query)["kpis"]["posts"] == expected
    assert posts(client, context, QUERY + '&' + query)["total"] == expected
    assert detail(client, context, p)["post"] == before


@pytest.mark.parametrize("media", ["TEXT", "IMAGE", "VIDEO", "CAROUSEL", "OTHER", None])
def test_media_and_null_category(client, context, media):
    add_post(context, media_type=media, metrics={"reach": 100, "likes": 1})
    a = analytics(client, context)
    assert a["media_type_performance"][0]["media_type"] == media
    if media:
        assert posts(client, context, QUERY + "&media_type=" + media)["total"] == 1
        other = "VIDEO" if media != "VIDEO" else "TEXT"
        assert posts(client, context, QUERY + "&media_type=" + other)["total"] == 0


def test_combined_filter_consistency(client, context):
    add_post(context, text="Agent", media_type="IMAGE", hashtags=["#Agent"], metrics={"likes": 10})
    add_post(context, text="Agent", media_type="VIDEO", hashtags=["#Other"], metrics={"likes": 100})
    query = QUERY + "&platform=X&keyword=agent&hashtag=Agent&media_type=IMAGE"
    assert analytics(client, context, query)["kpis"]["engagement"] == 10
    assert posts(client, context, query)["total"] == 1


def test_daily_utc_and_null_buckets(client, context):
    add_post(context, posted_at=datetime.fromisoformat("2026-10-02T01:00:00+09:00"), metrics={"likes": 5})
    add_post(context, posted_at=datetime.fromisoformat("2026-10-01T23:00:00Z"), metrics={"likes": 0})
    add_post(context, posted_at=datetime.fromisoformat("2026-10-02T12:00:00Z"))
    days = analytics(client, context)["engagement_trend"]
    assert [(d["date"], d["post_count"], d["engagement_total"], d["avg_engagement"]) for d in days] == [
        ("2026-10-01", 2, 5, 2.5), ("2026-10-02", 1, None, None), ("2026-10-03", 0, None, None)]


def test_pagination_default_stable_uuid_tiebreak(client, context):
    ids = [add_post(context, metrics={"reach": 100, "likes": i}) for i in range(25)]
    expected = sorted(map(str, ids), reverse=True)
    p1 = posts(client, context); p2 = posts(client, context, QUERY + '&page=2')
    assert [p["post_id"] for p in p1["items"] + p2["items"]] == expected
    assert p1["total"] == 25 and len(p1["items"]) == 20
    assert posts(client, context, QUERY + '&page_size=100')["total"] == 25
    assert posts(client, context, QUERY + '&page=1000')["items"] == []


@pytest.mark.parametrize("sort", ["posted_at", "reach", "likes", "comments", "shares", "saves", "engagement", "engagement_rate"])
@pytest.mark.parametrize("order", ["asc", "desc"])
def test_sort_whitelist_nulls_last(client, context, sort, order):
    add_post(context, metrics={"reach": 100, "likes": 20, "comments": 2, "shares": 3, "saves": 4}, posted_at=T1 - timedelta(hours=1))
    add_post(context, metrics={"reach": 50, "likes": 1, "comments": 1, "shares": 1, "saves": 1})
    add_post(context)
    result = posts(client, context, QUERY + f'&sort={sort}&order={order}')
    known = [p[sort] for p in result["items"] if p[sort] is not None]
    assert known == sorted(known, reverse=order == "desc")
    if sort != "posted_at": assert result["items"][-1][sort] is None


def test_detail_comparison_topics_and_filter_scope(client, context):
    high = add_post(context, metrics={"reach": 100, "likes": 30})
    add_post(context, metrics={"reach": 100, "likes": 10})
    add_post(context, metrics={"views": 10, "likes": 100})
    with context.factory() as s, s.begin():
        s.add(PostTopic(post_id=high, topic_id=context.topic_id, match_type="MANUAL", match_score=50))
    d = detail(client, context, high)
    assert d["comparison"]["rank"] == 1 and d["comparison"]["vs_average_rate"] == 50
    assert d["comparison"]["comparable_posts"] == 2 and d["comparison"]["total_posts"] == 3
    assert d["topics"][0]["topic_id"] == str(context.topic_id)
    d = detail(client, context, high, QUERY + "&keyword=missing")
    assert d["comparison"]["rank"] is None and d["comparison"]["total_posts"] == 0
    assert client.get(base(context) + f"/posts/{high}").status_code == 200


def test_detail_tied_rank_and_zero_average(client, context):
    first = add_post(context, metrics={"reach": 100, "likes": 0})
    add_post(context, metrics={"reach": 100, "likes": 0})
    d = detail(client, context, first)
    assert d["comparison"]["rank"] == 1 and d["comparison"]["vs_average_rate"] is None


def test_followers_asof_latest_null_and_no_multi_sum(client, context):
    with context.factory() as s, s.begin():
        s.add_all([AccountMetric(account_id=context.own_id, recorded_date=date(2026, 9, 1), followers=10, raw_metrics={}),
                   AccountMetric(account_id=context.own_id, recorded_date=END, followers=0, raw_metrics={}),
                   AccountMetric(account_id=context.own_id, recorded_date=END + timedelta(days=1), followers=999, raw_metrics={})])
    assert analytics(client, context)["kpis"]["followers"] == 0
    with context.factory() as s, s.begin():
        s.add(ProjectPlatform(project_id=context.project_id, platform="INSTAGRAM"))
        ig = SNSAccount(project_id=context.project_id, platform="INSTAGRAM", account_name="ig", account_role="OWN")
        s.add(ig); s.flush()
        s.add(AccountMetric(account_id=ig.account_id, recorded_date=END, followers=20, raw_metrics={}))
    k = analytics(client, context)["kpis"]
    assert k["followers"] is None and sorted(a["followers"] for a in k["followers_by_account"]) == [0, 20]
    assert analytics(client, context, QUERY + '&platform=INSTAGRAM')["kpis"]["followers"] == 20


def test_cross_project_and_missing_resources(client, context):
    own = add_post(context)
    with context.factory() as s, s.begin():
        other = Project(name="Other own scope"); s.add(other); s.flush(); other_id = other.project_id
    try:
        assert client.get(f"/api/v1/projects/{other_id}/posts/{own}").status_code == 404
        assert client.get(f"/api/v1/projects/{uuid4()}/accounts/own/analytics?{QUERY}").status_code == 404
        assert client.get(base(context) + f'/posts/{uuid4()}').status_code == 404
        assert client.get(f"/api/v1/projects/{other_id}/accounts/own/posts?{QUERY}").json()["total"] == 0
    finally:
        with context.factory() as s, s.begin(): s.execute(delete(Project).where(Project.project_id == other_id))


@pytest.mark.parametrize("query,status", [("from=2026-10-04&to=2026-10-01", 400), ("from=2000-01-01&to=2030-01-01", 400), (QUERY + '&platform=SQL', 422), (QUERY + '&media_type=SQL', 422), (QUERY + '&page=0', 422), (QUERY + '&page_size=101', 422), (QUERY + '&sort=DROP%20TABLE', 422), (QUERY + '&order=SQL', 422), (QUERY + '&hashtag=%23', 400), (QUERY + '&hashtag=foo%20bar', 400), (QUERY + '&hashtag=foo;bar', 400), ("", 422), ("from=bad&to=bad", 422)])
def test_invalid_queries(client, context, query, status):
    r = client.get(base(context) + '/accounts/own/posts?' + query)
    assert r.status_code == status
    assert "DROP TABLE" not in r.text and "SQL" not in r.text


def test_detail_incomplete_filter_dates(client, context):
    p = add_post(context)
    assert client.get(base(context) + f'/posts/{p}?from=2026-10-01').status_code == 400
    assert client.get(base(context) + f'/posts/{p}?keyword=test').status_code == 400


def test_safe_server_error(client, context, service, monkeypatch):
    def fail(*args): raise RuntimeError("postgresql://secret_password")
    monkeypatch.setattr(service.repository, "posts", fail)
    r = client.get(base(context) + '/accounts/own/analytics?' + QUERY)
    assert r.status_code == 500 and "secret" not in r.text and "postgresql" not in r.text


def test_read_only_database_transaction_and_n_plus_one(client, context):
    with context.factory() as s, s.begin():
        ps = [SNSPost(project_id=context.project_id, account_id=context.own_id, source_type="OWN", platform="X", platform_post_id=str(i), posted_at=T1, text="Bulk", hashtags=[], raw_data={}) for i in range(1000)]
        s.add_all(ps); s.flush()
        s.add_all([PostMetric(post_id=p.post_id, recorded_at=T1, likes=1, reach=100, raw_metrics={}) for p in ps])
    engine = context.factory.kw["bind"]; statements = []
    def capture(conn, cursor, statement, parameters, ctx, many):
        if statement.lstrip().upper().startswith("SELECT"): statements.append(statement)
        assert not statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
    event.listen(engine, "before_cursor_execute", capture)
    try:
        a = analytics(client, context)
        analytics_queries = len(statements); statements.clear()
        p = posts(client, context); list_queries = len(statements)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert a["kpis"]["posts"] == p["total"] == 1000
    assert a["kpis"]["engagement"] == 1000
    assert analytics_queries <= 4 and list_queries <= 3
    with service_read(context) as s:
        assert s.connection().exec_driver_sql("SHOW transaction_read_only").scalar() == "on"
        assert s.connection().exec_driver_sql("SHOW transaction_isolation").scalar() == "repeatable read"


def service_read(context):
    return MyAccountService(context.factory).read(context.project_id)
