from datetime import datetime, timedelta, timezone
from decimal import Decimal as N
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update

from app.db.models import PostMetric, PostTerm, PostTopic, Project, ProjectPlatform, SNSPost, TrendDaily, WatchTerm, WatchTopic
from app.repositories.trend_repository import MarketFact, TrendInputs
from app.services.trend_service import TrendService, build_trend_rows


FIRST = datetime(2026, 1, 1, tzinfo=timezone.utc)


def add_post(session, context, day=0, likes=10, source="MARKET", platform="X", topic_id=None,
             term_ids=None, posted_at=None, snapshot=True, method="KEYWORD", term_method="NORMALIZED"):
    post = SNSPost(project_id=context.project_id, platform=platform, platform_post_id=str(uuid4()),
                   source_type=source, posted_at=posted_at or FIRST + timedelta(days=day))
    session.add(post)
    session.flush()
    if snapshot:
        session.add(PostMetric(post_id=post.post_id, recorded_at=FIRST, likes=likes))
    session.add(PostTopic(post_id=post.post_id, topic_id=topic_id or context.topic_id, match_type=method))
    for term_id in term_ids if term_ids is not None else [context.terms["AI"]]:
        session.add(PostTerm(post_id=post.post_id, term_id=term_id, match_method=term_method))
    return post


def rebuild(context):
    with context.factory() as session, session.begin():
        count = TrendService().rebuild_project(session, context.project_id)
    with context.factory() as session:
        rows = list(session.scalars(select(TrendDaily).join(WatchTopic).where(WatchTopic.project_id == context.project_id)))
    assert len(rows) == count
    return rows


def find(rows, context, day=0, term_id=None, platform="X"):
    return next(row for row in rows if row.topic_id == context.topic_id and row.term_id == term_id and
                row.platform == platform and row.trend_date == (FIRST + timedelta(days=day)).date())


def test_latest_snapshot_topic_dedup_term_grains(context):
    with context.factory() as session, session.begin():
        post = add_post(session, context, likes=10, term_ids=[context.terms["AI"], context.terms["ChatGPT"]])
        session.add(PostMetric(post_id=post.post_id, recorded_at=FIRST + timedelta(days=1), likes=30, comments=2, shares=3, saves=4))
    rows = rebuild(context)
    assert len(rows) == 6  # 1 topic and 5 active terms, partial uniques coexist.
    topic = find(rows, context)
    assert topic.post_count == 1 and topic.engagement_count == 39 and topic.avg_engagement == N("39.0000")
    for term_id in (context.terms["AI"], context.terms["ChatGPT"]):
        term = find(rows, context, term_id=term_id)
        assert term.post_count == 1 and term.engagement_count == 39
    assert topic.trend_score is None and topic.acceleration_rate is None


@pytest.mark.parametrize("method,term_method", [("MANUAL", "MANUAL"), ("AI", "AI"), ("HASHTAG", "EXACT")])
def test_formal_matches_included_without_weighting(context, method, term_method):
    with context.factory() as session, session.begin():
        add_post(session, context, method=method, term_method=term_method)
    rows = rebuild(context)
    assert find(rows, context).post_count == 1
    assert find(rows, context, term_id=context.terms["AI"]).engagement_count == 10


def test_market_only(context):
    with context.factory() as session, session.begin():
        for source in ("OWN", "COMPETITOR", "MARKET"):
            add_post(session, context, likes=100, source=source)
    topic = find(rebuild(context), context)
    assert topic.post_count == 1 and topic.engagement_count == 100


def test_missing_snapshot_and_unknown_zero_average(context):
    with context.factory() as session, session.begin():
        add_post(session, context, likes=10)
        add_post(session, context, snapshot=False)
        add_post(session, context, likes=20)
        add_post(session, context, likes=None)
    topic = find(rebuild(context), context)
    assert topic.post_count == 4 and topic.engagement_count == 30 and topic.avg_engagement == N("15.0000")


@pytest.mark.parametrize("likes,avg,score", [(None, None, None), (0, N("0.0000"), N("50.00"))])
def test_all_unknown_vs_explicit_zero(context, likes, avg, score):
    with context.factory() as session, session.begin():
        add_post(session, context, likes=likes)
    topic = find(rebuild(context), context)
    assert topic.engagement_count == 0 and topic.avg_engagement == avg
    assert topic.engagement_level_score == score


def test_continuous_dates_and_zero_window_rows(context):
    with context.factory() as session, session.begin():
        add_post(session, context, day=0)
        add_post(session, context, day=20)
    rows = rebuild(context)
    assert len(rows) == 21 * 6
    assert {row.trend_date for row in rows} == {(FIRST + timedelta(days=d)).date() for d in range(21)}
    empty = find(rows, context, day=7)
    assert empty.post_count == empty.engagement_count == 0 and empty.avg_engagement is None
    assert empty.post_growth_rate == N("-100.0000") and empty.engagement_growth_rate is None
    assert find(rows, context, day=6).post_count == 1


def test_inclusive_three_window_boundaries_and_acceleration(context):
    # D=20: prior 0..6 has10, previous7..13 has15, current14..20 has30.
    with context.factory() as session, session.begin():
        for day, count in ((0, 5), (6, 5), (7, 7), (13, 8), (14, 14), (20, 16)):
            for _ in range(count):
                add_post(session, context, day=day, likes=1)
    topic = find(rebuild(context), context, day=20)
    assert topic.post_count == topic.engagement_count == 30
    assert topic.post_growth_rate == topic.engagement_growth_rate == N("100.0000")
    assert topic.acceleration_rate == N("50.0000")
    assert (topic.post_growth_score, topic.engagement_growth_score, topic.engagement_level_score,
            topic.acceleration_score, topic.trend_score) == (N("50.00"),) * 5


def test_utc_independent_of_session_timezone(context):
    with context.factory() as session, session.begin():
        add_post(session, context, posted_at=datetime.fromisoformat("2026-01-02T00:30:00+09:00"))
    with context.factory() as session, session.begin():
        from sqlalchemy import text
        session.execute(text("SET LOCAL TIME ZONE 'Pacific/Honolulu'"))
        TrendService().rebuild_project(session, context.project_id)
    rows = rebuild(context)
    assert {row.trend_date for row in rows} == {FIRST.date()}


def test_platform_separation_and_disabled_platform(context):
    with context.factory() as session, session.begin():
        session.add(ProjectPlatform(project_id=context.project_id, platform="INSTAGRAM"))
        add_post(session, context, likes=10, platform="X")
        add_post(session, context, likes=100, platform="INSTAGRAM")
    rows = rebuild(context)
    assert len(rows) == 12
    assert find(rows, context, platform="X").engagement_count == 10
    assert find(rows, context, platform="INSTAGRAM").engagement_count == 100
    # Each platform's only known topic level is neutral, never 0/100 across platforms.
    assert find(rows, context, platform="X").engagement_level_score == N("50.00")
    assert find(rows, context, platform="INSTAGRAM").engagement_level_score == N("50.00")
    with context.factory() as session, session.begin():
        session.execute(delete(ProjectPlatform).where(ProjectPlatform.project_id == context.project_id,
                                                     ProjectPlatform.platform == "INSTAGRAM"))
    assert {row.platform for row in rebuild(context)} == {"X"}


@pytest.mark.parametrize("target", ["topic", "term"])
def test_inactive_materialization_removed(context, target):
    with context.factory() as session, session.begin():
        add_post(session, context)
    assert len(rebuild(context)) == 6
    with context.factory() as session, session.begin():
        if target == "topic":
            session.execute(update(WatchTopic).where(WatchTopic.topic_id == context.topic_id).values(is_active=False))
        else:
            session.execute(update(WatchTerm).where(WatchTerm.term_id == context.terms["AI"]).values(is_active=False))
    rows = rebuild(context)
    assert len(rows) == (0 if target == "topic" else 5)
    assert not any(row.term_id == context.terms["AI"] for row in rows)


def test_empty_market_clears_current_project_only(context):
    with context.factory() as session, session.begin():
        add_post(session, context)
    rebuild(context)
    with context.factory() as session, session.begin():
        session.execute(delete(SNSPost).where(SNSPost.project_id == context.project_id))
    assert not rebuild(context)


def test_project_isolation_even_with_cross_project_links(context):
    with context.factory() as session, session.begin():
        other = Project(name="Other")
        session.add(other)
        session.flush()
        topic = WatchTopic(project_id=other.project_id, topic_name="AI")
        session.add(topic)
        session.flush()
        other_term = WatchTerm(topic_id=topic.topic_id, term="AI", normalized_term="ai", term_type="KEYWORD")
        session.add(other_term)
        session.flush()
        kept = TrendDaily(topic_id=topic.topic_id, platform="X", trend_date=FIRST.date(), post_count=123)
        session.add(kept)
        add_post(session, context, topic_id=topic.topic_id, term_ids=[other_term.term_id])  # Cross-project links must not leak.
    try:
        rows = rebuild(context)
        assert all(row.post_count == 0 for row in rows)
        with context.factory() as session:
            other_row = session.get(TrendDaily, kept.trend_daily_id)
            assert other_row.post_count == 123
        with context.factory() as session, session.begin():
            session.execute(delete(SNSPost).where(SNSPost.project_id == context.project_id))
        assert not rebuild(context)
        with context.factory() as session:
            assert session.get(TrendDaily, kept.trend_daily_id).post_count == 123
    finally:
        with context.factory() as session, session.begin():
            session.execute(delete(Project).where(Project.project_id == other.project_id))


def semantic_rows(rows):
    fields = ("topic_id", "term_id", "platform", "trend_date", "window_days", "post_count", "engagement_count",
              "avg_engagement", "post_growth_rate", "engagement_growth_rate", "acceleration_rate",
              "post_growth_score", "engagement_growth_score", "engagement_level_score", "acceleration_score", "trend_score")
    return {tuple(str(getattr(row, field)) for field in fields) for row in rows}


def test_rebuild_idempotency(context):
    with context.factory() as session, session.begin():
        add_post(session, context)
        add_post(session, context, day=2, likes=20)
    first = rebuild(context)
    second = rebuild(context)
    assert len(first) == len(second) == 18 and semantic_rows(first) == semantic_rows(second)


def test_no_platforms_or_topics_and_nonexistent_project(context):
    with context.factory() as session, session.begin():
        add_post(session, context)
        session.execute(delete(ProjectPlatform).where(ProjectPlatform.project_id == context.project_id))
    assert not rebuild(context)
    with context.factory() as session, session.begin():
        with pytest.raises(ValueError):
            TrendService().rebuild_project(session, uuid4())


def test_no_commit_inside_rebuild_and_partial_insert_rollback(context):
    with context.factory() as session, session.begin():
        add_post(session, context)
    original = rebuild(context)
    from app.repositories.trend_repository import TrendRepository
    class BrokenRepository(TrendRepository):
        def replace(self, session, project_id, rows):
            super().replace(session, project_id, rows[:1])
            raise RuntimeError("failure after delete and first insert")
    with pytest.raises(RuntimeError):
        with context.factory() as session, session.begin():
            TrendService(BrokenRepository()).rebuild_project(session, context.project_id)
    with context.factory() as session:
        remaining = list(session.scalars(select(TrendDaily)))
    assert {row.trend_daily_id for row in remaining} == {row.trend_daily_id for row in original}
    assert semantic_rows(remaining) == semantic_rows(original)


def test_separate_topic_term_normalization_cohorts():
    topics, terms = [uuid4(), uuid4()], [uuid4(), uuid4()]
    posts = [MarketFact(uuid4(), "X", FIRST, value, None, None, None) for value in (10, 20, 100, 200)]
    inputs = TrendInputs(["X"], topics, dict(zip(terms, topics)), posts,
                         [(posts[i].post_id, topics[i]) for i in range(2)],
                         [(posts[i + 2].post_id, terms[i]) for i in range(2)])
    rows = build_trend_rows(inputs)
    assert {row["topic_id"]: row["engagement_level_score"] for row in rows if row["term_id"] is None} == dict(zip(topics, [N(0), N(100)]))
    assert {row["term_id"]: row["engagement_level_score"] for row in rows if row["term_id"]} == dict(zip(terms, [N(0), N(100)]))


def test_daily_and_window_growth_total_not_average():
    topic = uuid4()
    posts = [MarketFact(uuid4(), "X", FIRST + timedelta(days=d), engagement, None, None, None)
             for d, engagement in ((0, 100), (7, 100), (7, 50))]
    rows = build_trend_rows(TrendInputs(["X"], [topic], {}, posts, [(p.post_id, topic) for p in posts], []))
    last = rows[-1]
    assert last["post_growth_rate"] == N("100.0000")
    assert last["engagement_growth_rate"] == N("50.0000")  # Avg growth would be -25.
    assert last["avg_engagement"] == N("75.0000")


def test_large_input_prefix_aggregation():
    topic, term = uuid4(), uuid4()
    posts = [MarketFact(uuid4(), "X", FIRST + timedelta(days=i % 90), 10, None, None, None) for i in range(10000)]
    inputs = TrendInputs(["X"], [topic], {term: topic}, posts,
                         [(p.post_id, topic) for p in posts], [(p.post_id, term) for p in posts])
    rows = build_trend_rows(inputs)
    assert len(rows) == 180
    topic_last = next(row for row in rows if row["trend_date"] == (FIRST + timedelta(days=89)).date() and row["term_id"] is None)
    expected = sum(83 <= i % 90 <= 89 for i in range(10000))
    assert topic_last["post_count"] == expected and topic_last["engagement_count"] == expected * 10
