"""Constraint and deletion behavior against a disposable real PostgreSQL DB."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import CheckConstraint, delete, func, inspect, select, text, update
from sqlalchemy.exc import IntegrityError

from app.db.base import Base
from app.db.models import (
    AccountMetric, AIInsight, ImportHistory, PostMetric, PostTerm, PostTopic,
    Project, ProjectPlatform, SNSAccount, SNSPost, TrendDaily, WatchTerm, WatchTopic,
    ProviderConnection, ProviderSyncState, JobRun, JobStep, JobSchedule,
)

TODAY = date(2026, 10, 3)
NOW = datetime(2026, 10, 3, 9, tzinfo=timezone.utc)


def add(session, model, **values):
    return session.execute(model.__table__.insert().values(**values).returning(model.__table__)).mappings().one()


def rejects(session, operation, state):
    with pytest.raises(IntegrityError) as error:
        with session.begin_nested():
            operation()
    assert error.value.orig.sqlstate == state


@pytest.fixture
def graph(database):
    project = add(database, Project, name="Test project")
    pid = project["project_id"]
    provider = add(database, ProviderConnection, project_id=pid, provider_type="X_API")
    job = add(database, JobRun, project_id=pid, data_mode='DEMO', provider_connection_id=provider['id'], job_type='PROVIDER_SYNC')
    add(database, JobStep, job_run_id=job['id'], step_type='PROVIDER_SYNC', sequence_no=1)
    add(database, JobSchedule, project_id=pid, provider_connection_id=provider['id'], schedule_mode='INTERVAL', interval_seconds=3600, schedule_scope_key=f'project:{pid}:provider:{provider["id"]}:PROVIDER_SYNC_PIPELINE')
    add(database, ProviderSyncState, provider_connection_id=provider["id"], sync_resource_type="POSTS")
    add(database, ProjectPlatform, project_id=pid, platform="X")
    account = add(database, SNSAccount, project_id=pid, platform="X", account_name="own", account_role="OWN")
    aid = account["account_id"]
    add(database, AccountMetric, account_id=aid, recorded_date=TODAY)
    post = add(database, SNSPost, project_id=pid, account_id=aid, platform="X", source_type="OWN", platform_post_id="1", posted_at=NOW)
    postid = post["post_id"]
    add(database, PostMetric, post_id=postid, recorded_at=NOW)
    topic = add(database, WatchTopic, project_id=pid, topic_name="Test topic")
    tid = topic["topic_id"]
    term = add(database, WatchTerm, topic_id=tid, term="Test", normalized_term="test", term_type="KEYWORD")
    termid = term["term_id"]
    add(database, PostTopic, post_id=postid, topic_id=tid, match_type="KEYWORD")
    add(database, PostTerm, post_id=postid, term_id=termid, match_method="EXACT")
    topictrend = add(database, TrendDaily, topic_id=tid, platform="X", trend_date=TODAY)
    termtrend = add(database, TrendDaily, topic_id=tid, term_id=termid, platform="X", trend_date=TODAY)
    history = add(database, ImportHistory, project_id=pid, import_type="OWN_POSTS", filename="test.csv", status="SUCCESS")
    insight = add(database, AIInsight, project_id=pid, analysis_from=TODAY, analysis_to=TODAY, content={"summary": "テスト"})
    return dict(project=project, account=account, post=post, topic=topic, term=term,
                topictrend=topictrend, termtrend=termtrend, history=history, insight=insight)


def count(session, table):
    return session.scalar(select(func.count()).select_from(table))


def test_schema_matches_models(postgres_engine):
    with postgres_engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection, opts={"compare_type": True, "compare_server_default": True}), Base.metadata) == []
        inspector = inspect(connection)
        assert set(inspector.get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
        assert len(Base.metadata.tables) == 18
        for table in Base.metadata.tables.values():
            # Alembic autogeneration does not compare CHECK expressions; check their catalog names too.
            assert {c["name"] for c in inspector.get_check_constraints(table.name)} == {
                c.name for c in table.constraints if isinstance(c, CheckConstraint)
            }
            assert set(inspector.get_pk_constraint(table.name)["constrained_columns"]) == {c.name for c in table.primary_key}
            actual = {(tuple(f["constrained_columns"]), f["referred_table"], f["options"]["ondelete"]) for f in inspector.get_foreign_keys(table.name)}
            expected = {(tuple(c.name for c in f.columns), f.elements[0].column.table.name, f.ondelete) for f in table.foreign_key_constraints}
            assert actual == expected
        indexes = dict(connection.execute(text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='public'")).all())
        assert "WHERE" in indexes["uq_sns_accounts_one_own_per_platform"]
        for name in ("uq_trend_daily_topic_window", "uq_trend_daily_term_window"):
            assert "UNIQUE" in indexes[name] and "window_days" in indexes[name] and "WHERE" in indexes[name]
        assert "DESC" in indexes["idx_trend_daily_platform_date_score"]


def test_uuid_jsonb_timestamps_and_defaults(database, graph):
    assert isinstance(graph["project"]["project_id"], uuid.UUID)
    assert graph["project"]["created_at"].utcoffset() is not None
    assert graph["project"]["updated_at"].utcoffset() is not None
    assert graph["project"]["is_active"] is True
    assert graph["post"]["hashtags"] == [] and graph["post"]["raw_data"] == {}
    assert graph["topictrend"]["window_days"] == 7
    assert graph["topictrend"]["post_count"] == 0
    assert graph["history"]["error_detail"] == []
    row = add(database, AIInsight, project_id=graph["project"]["project_id"], platform=None,
              analysis_from=TODAY, analysis_to=TODAY, content={"日本語": [1, True, None]},
              evidence={"ids": ["p1"]}, input_summary={"count": 1})
    fetched = database.execute(select(AIInsight.__table__).where(AIInsight.insight_id == row["insight_id"])).mappings().one()
    for field in ("content", "evidence", "input_summary"):
        assert fetched[field] == row[field]
        assert database.scalar(text(f"SELECT pg_typeof({field})::text FROM ai_insights LIMIT 1")) == "jsonb"
    metric = database.execute(select(AccountMetric.__table__)).mappings().one()
    assert metric["raw_metrics"] == {}
    # JSONB distinguishes SQL NULL from JSON null; enforce the declared SQL NOT NULL.
    rejects(database, lambda: database.execute(text("UPDATE account_metrics SET raw_metrics=NULL")), "23502")


def test_market_without_account(database, graph):
    row = add(database, SNSPost, project_id=graph["project"]["project_id"], account_id=None,
              platform="X", source_type="MARKET", platform_post_id="market", posted_at=NOW)
    assert row["account_id"] is None


def test_own_partial_unique(database, graph):
    pid = graph["project"]["project_id"]
    def account(name, platform="X", role="OWN", **extra):
        return add(database, SNSAccount, project_id=pid, platform=platform, account_name=name, account_role=role, **extra)
    rejects(database, lambda: account("second-own"), "23505")
    database.execute(update(SNSAccount).where(SNSAccount.account_id == graph["account"]["account_id"]).values(is_active=False))
    account("replacement")
    account("inactive", is_active=False)
    account("instagram-own", "INSTAGRAM")
    account("competitor1", role="COMPETITOR")
    account("competitor2", role="COMPETITOR")
    other = add(database, Project, name="Other project")
    add(database, SNSAccount, project_id=other["project_id"], platform="X", account_name="own", account_role="OWN")


@pytest.mark.parametrize("parent,removed", [
    ("project", set(Base.metadata.tables)),
    ("account", {"sns_accounts", "account_metrics"}),
    ("post", {"sns_posts", "post_metrics", "post_topics", "post_terms"}),
    ("topic", {"watch_topics", "watch_terms", "post_topics", "post_terms", "trend_daily"}),
    ("term", {"watch_terms", "post_terms"}),
])
def test_delete_cascade_and_set_null(database, graph, parent, removed):
    models = {"project": Project, "account": SNSAccount, "post": SNSPost, "topic": WatchTopic, "term": WatchTerm}
    model = models[parent]
    pk = next(iter(model.__table__.primary_key))
    database.execute(delete(model).where(pk == graph[parent][pk.name]))
    for name, table in Base.metadata.tables.items():
        expected = 0 if name in removed else (2 if name == "trend_daily" else 1)
        if parent == "term" and name == "trend_daily":
            expected = 1
        assert count(database, table) == expected, name
    if parent == "account":
        assert database.scalar(select(SNSPost.account_id)) is None


UNIQUE_CASES = [
    (ProjectPlatform, {"project_id": ("project", "project_id"), "platform": "X"}),
    (SNSAccount, {"project_id": ("project", "project_id"), "platform": "X", "account_name": "own", "account_role": "COMPETITOR"}),
    (AccountMetric, {"account_id": ("account", "account_id"), "recorded_date": TODAY}),
    (SNSPost, {"project_id": ("project", "project_id"), "platform": "X", "platform_post_id": "1", "source_type": "MARKET", "posted_at": NOW}),
    (PostMetric, {"post_id": ("post", "post_id"), "recorded_at": NOW}),
    (WatchTopic, {"project_id": ("project", "project_id"), "topic_name": "Test topic"}),
    (WatchTerm, {"topic_id": ("topic", "topic_id"), "term_type": "KEYWORD", "normalized_term": "test", "term": "different"}),
    (PostTopic, {"post_id": ("post", "post_id"), "topic_id": ("topic", "topic_id"), "match_type": "MANUAL"}),
    (PostTerm, {"post_id": ("post", "post_id"), "term_id": ("term", "term_id"), "match_method": "MANUAL"}),
    (TrendDaily, {"topic_id": ("topic", "topic_id"), "platform": "X", "trend_date": TODAY}),
    (TrendDaily, {"topic_id": ("topic", "topic_id"), "term_id": ("term", "term_id"), "platform": "X", "trend_date": TODAY}),
]


@pytest.mark.parametrize("model,values", UNIQUE_CASES, ids=[f"{m.__tablename__}-{i}" for i, (m, _) in enumerate(UNIQUE_CASES)])
def test_unique_constraints(database, graph, model, values):
    resolved = {k: graph[v[0]][v[1]] if isinstance(v, tuple) else v for k, v in values.items()}
    rejects(database, lambda: add(database, model, **resolved), "23505")


METRICS = [(AccountMetric, field) for field in ("followers", "following", "post_count")] + [
    (PostMetric, field) for field in ("impressions", "reach", "views", "likes", "comments", "shares", "saves")]


@pytest.mark.parametrize("model,field", METRICS, ids=[f"{m.__tablename__}-{f}" for m, f in METRICS])
@pytest.mark.parametrize("value", [None, 0, -1])
def test_metric_counts(database, graph, model, field, value):
    operation = lambda: database.execute(update(model).values({field: value}))
    if value == -1:
        rejects(database, operation, "23514")
    else:
        operation()
        assert database.scalar(select(getattr(model, field))) == value


SCORES = [(PostTopic, "match_score"), (PostTerm, "match_score")] + [
    (TrendDaily, field) for field in ("post_growth_score", "engagement_growth_score", "engagement_level_score", "acceleration_score", "trend_score")]


@pytest.mark.parametrize("model,field", SCORES, ids=[f"{m.__tablename__}-{f}" for m, f in SCORES])
@pytest.mark.parametrize("value", [None, Decimal("0"), Decimal("100"), Decimal("-0.01"), Decimal("100.01")])
def test_score_boundaries(database, graph, model, field, value):
    operation = lambda: database.execute(update(model).values({field: value}))
    if value is not None and (value < 0 or value > 100):
        rejects(database, operation, "23514")
    else:
        operation()
        assert database.scalar(select(getattr(model, field)).limit(1)) == value


ENUMS = [
    (ProjectPlatform, "platform", ["X", "INSTAGRAM"]), (SNSAccount, "platform", ["X", "INSTAGRAM"]),
    (SNSAccount, "account_role", ["OWN", "COMPETITOR"]), (SNSPost, "platform", ["X", "INSTAGRAM"]),
    (SNSPost, "source_type", ["OWN", "COMPETITOR", "MARKET"]),
    (SNSPost, "media_type", [None, "TEXT", "IMAGE", "VIDEO", "CAROUSEL", "OTHER"]),
    (WatchTerm, "term_type", ["KEYWORD", "HASHTAG"]),
    (PostTopic, "match_type", ["KEYWORD", "HASHTAG", "AI", "MANUAL"]),
    (PostTerm, "match_method", ["EXACT", "NORMALIZED", "MANUAL", "AI"]),
    (TrendDaily, "platform", ["X", "INSTAGRAM"]),
    (ImportHistory, "import_type", ["OWN_POSTS", "ACCOUNT_DAILY", "TREND_POSTS", "COMPETITOR_POSTS"]),
    (ImportHistory, "status", ["PROCESSING", "SUCCESS", "PARTIAL_ERROR", "FAILED"]),
    (AIInsight, "platform", [None, "X", "INSTAGRAM"]),
]


@pytest.mark.parametrize("model,field,values", ENUMS, ids=[f"{m.__tablename__}-{f}" for m, f, _ in ENUMS])
def test_enumerations(database, graph, model, field, values):
    for value in values:
        database.execute(update(model).values({field: value}))
    rejects(database, lambda: database.execute(update(model).values({field: "INVALID"})), "23514")


@pytest.mark.parametrize("field", ["post_growth_rate", "engagement_growth_rate", "acceleration_rate"])
def test_negative_growth_is_allowed(database, graph, field):
    database.execute(update(TrendDaily).values({field: Decimal("-125.4321")}))
    assert database.scalar(select(getattr(TrendDaily, field)).limit(1)) == Decimal("-125.4321")


@pytest.mark.parametrize("model,field", [(TrendDaily, "post_count"), (TrendDaily, "engagement_count"),
    (TrendDaily, "avg_engagement"), (ImportHistory, "total_count"), (ImportHistory, "success_count"), (ImportHistory, "error_count")])
def test_nonnegative_counts(database, graph, model, field):
    rejects(database, lambda: database.execute(update(model).values({field: -1})), "23514")
    database.execute(update(model).values({field: 0}))


def test_window_and_analysis_period(database, graph):
    rejects(database, lambda: database.execute(update(TrendDaily).values(window_days=30)), "23514")
    rejects(database, lambda: database.execute(update(AIInsight).values(analysis_to=date(2026, 10, 2))), "23514")
    database.execute(update(AIInsight).values(analysis_to=date(2026, 10, 4)))
    # No unapproved sum-of-counts check.
    database.execute(update(ImportHistory).values(total_count=1, success_count=10, error_count=5))


def test_foreign_keys_reject_missing_parent(database, graph):
    for table in Base.metadata.tables.values():
        for foreign_key in table.foreign_keys:
            column = foreign_key.parent
            row = database.execute(select(table).limit(1)).mappings().one()
            condition = [c == row[c.name] for c in table.primary_key]
            rejects(database, lambda t=table, c=column, conditions=condition:
                    database.execute(t.update().where(*conditions).values({c.name: uuid.uuid4()})), "23503")
