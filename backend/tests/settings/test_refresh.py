from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import pytest
from sqlalchemy import delete, event, select

from app.db.models import ImportHistory, PostTerm, PostTopic, Project, ProjectPlatform, SNSPost, TrendDaily, WatchTerm, WatchTopic
from app.providers.base import CsvDatasetType as D
from app.schemas.settings import Platforms, TermCreate, TermPatch, TopicPatch
from app.services.settings_service import SettingsFailure, SettingsService
from tests.imports.conftest import T1
from tests.imports.test_pipeline import run_import, values
from tests.providers.helpers import csv_text, row


@pytest.mark.parametrize("dataset,account", [(D.OWN_POSTS, "dummy_demo"), (D.COMPETITOR_POSTS, "competitor"), (D.TREND_POSTS, "")])
@pytest.mark.parametrize("source", ["text", "keyword", "hashtag"])
def test_existing_posts_rematch_all_sources(settings, context, tmp_path, dataset, account, source):
    options = {"account_name": account}
    if source == "text": options["text"] = "NewAgent活用"
    if source == "keyword": options["keyword"] = "NewAgent"
    if source == "hashtag": options["hashtags"] = "#NewAgent"
    # Only TREND_POSTS has an explicit keyword field; body/hashtags work for all sources.
    if source == "keyword" and dataset != D.TREND_POSTS:
        options["text"] = "NewAgent活用"
    run_import(context, tmp_path, dataset, [row(dataset, **options)])
    if source == "hashtag" and dataset == D.COMPETITOR_POSTS:
        # Competitor CSV has no hashtags column, but stored posts may have hashtags.
        with context.factory() as s, s.begin():
            post = s.scalar(select(SNSPost).where(SNSPost.project_id == context.project_id))
            post.hashtags = ["#NewAgent"]
    before = values(context, SNSPost)[0]
    assert not values(context, PostTerm)
    term = settings.create_term(context.project_id, context.topic_id, TermCreate(term="NewAgent", term_type="HASHTAG" if source == "hashtag" else "KEYWORD"))
    matches = values(context, PostTerm)
    assert len(matches) == 1 and matches[0].term_id == term.term_id
    assert values(context, PostTopic)[0].topic_id == context.topic_id
    after = values(context, SNSPost)[0]
    assert (after.text, after.hashtags, after.raw_data, after.updated_at) == (before.text, before.hashtags, before.raw_data, before.updated_at)
    if dataset == D.TREND_POSTS:
        assert any(t.term_id == term.term_id and t.post_count == 1 for t in values(context, TrendDaily))


@pytest.mark.parametrize("kind", ["MANUAL", "AI"])
@pytest.mark.parametrize("target", ["term", "topic"])
def test_deactivate_preserves_protected_matches(settings, context, tmp_path, kind, target):
    run_import(context, tmp_path, D.TREND_POSTS, [row(D.TREND_POSTS, keyword="ChatGPT", text="ChatGPT")])
    post = values(context, SNSPost)[0]
    with context.factory() as s, s.begin():
        protected = WatchTopic(project_id=context.project_id, topic_name="Protected")
        s.add(protected); s.flush()
        term = WatchTerm(topic_id=protected.topic_id, term="Protected", normalized_term="protected", term_type="KEYWORD")
        s.add(term); s.flush(); term_id = term.term_id
        s.add_all([PostTerm(post_id=post.post_id, term_id=term_id, match_method=kind, match_score=42),
                   PostTopic(post_id=post.post_id, topic_id=protected.topic_id, match_type=kind, match_score=43)])
    if target == "term":
        settings.patch_term(context.project_id, context.topic_id, context.terms["ChatGPT"], TermPatch(is_active=False))
    else:
        settings.patch_topic(context.project_id, context.topic_id, TopicPatch(is_active=False))
    terms = values(context, PostTerm)
    assert len(terms) == 1 and terms[0].match_method == kind and terms[0].match_score == 42
    topics = values(context, PostTopic)
    assert len(topics) == 1 and topics[0].match_type == kind and topics[0].match_score == 43
    assert not any(t.term_id == context.terms["ChatGPT"] for t in values(context, TrendDaily))
    if target == "term":
        settings.patch_term(context.project_id, context.topic_id, context.terms["ChatGPT"], TermPatch(is_active=True))
    else:
        settings.patch_topic(context.project_id, context.topic_id, TopicPatch(is_active=True))
    assert any(t.term_id == context.terms["ChatGPT"] for t in values(context, PostTerm))


def test_term_rename_and_type_refresh(settings, context, tmp_path):
    run_import(context, tmp_path, D.TREND_POSTS, [row(D.TREND_POSTS, text="ChatGPT", hashtags="#Claude")])
    settings.patch_term(context.project_id, context.topic_id, context.terms["ChatGPT"], TermPatch(term="Claude"))
    assert not values(context, PostTerm)
    result = settings.patch_term(context.project_id, context.topic_id, context.terms["ChatGPT"], TermPatch(term_type="HASHTAG"))
    assert result.term == "#Claude" and result.normalized_term == "#claude"
    assert values(context, PostTerm)[0].term_id == result.term_id


def test_topic_metadata_does_not_refresh(context):
    rematch = Mock()
    service = SettingsService(context.factory, rematch=rematch)
    service.patch_topic(context.project_id, context.topic_id, TopicPatch(topic_name="Rename", description="Change"))
    rematch.refresh_project.assert_not_called()


def test_platform_refresh_restores_existing_data(settings, context, tmp_path):
    settings.put_platforms(context.project_id, Platforms(platforms=["X", "INSTAGRAM"]))
    run_import(context, tmp_path, D.TREND_POSTS, [row(D.TREND_POSTS, post_id="x", keyword="AI"), row(D.TREND_POSTS, platform="INSTAGRAM", post_id="ig", keyword="AI")])
    assert {t.platform for t in values(context, TrendDaily)} == {"X", "INSTAGRAM"}
    settings.put_platforms(context.project_id, Platforms(platforms=["X"]))
    assert {t.platform for t in values(context, TrendDaily)} == {"X"}
    assert len(values(context, SNSPost)) == 2
    assert len(values(context, ImportHistory)) == 1
    settings.put_platforms(context.project_id, Platforms(platforms=["X", "INSTAGRAM"]))
    assert {t.platform for t in values(context, TrendDaily)} == {"X", "INSTAGRAM"}


@pytest.mark.parametrize("operation", ["create_term", "patch_term", "patch_topic", "platform"])
def test_refresh_failure_rolls_back_everything(context, tmp_path, operation):
    run_import(context, tmp_path, D.TREND_POSTS, [row(D.TREND_POSTS, keyword="ChatGPT")])
    before_terms = [(t.term_id, t.match_method) for t in values(context, PostTerm)]
    before_trend = [(t.trend_daily_id, t.post_count) for t in values(context, TrendDaily)]
    deleted = []
    class FailingTrend:
        def rebuild_project(self, s, project_id):
            result = s.execute(delete(TrendDaily).where(TrendDaily.topic_id.in_(
                select(WatchTopic.topic_id).where(WatchTopic.project_id == project_id))))
            deleted.append(result.rowcount)
            raise RuntimeError("secret database internals")
    service = SettingsService(context.factory, trend=FailingTrend())
    with pytest.raises(SettingsFailure) as error:
        if operation == "create_term": service.create_term(context.project_id, context.topic_id, TermCreate(term="new", term_type="KEYWORD"))
        if operation == "patch_term": service.patch_term(context.project_id, context.topic_id, context.terms["ChatGPT"], TermPatch(is_active=False))
        if operation == "patch_topic": service.patch_topic(context.project_id, context.topic_id, TopicPatch(is_active=False))
        if operation == "platform": service.put_platforms(context.project_id, Platforms(platforms=["INSTAGRAM"]))
    assert error.value.status == 500 and "secret" not in error.value.message
    assert deleted and deleted[0] > 0
    assert [(t.term_id, t.match_method) for t in values(context, PostTerm)] == before_terms
    assert [(t.trend_daily_id, t.post_count) for t in values(context, TrendDaily)] == before_trend
    with context.factory() as s:
        assert s.get(WatchTerm, context.terms["ChatGPT"]).is_active
        assert s.get(WatchTopic, context.topic_id).is_active
        assert not s.scalar(select(WatchTerm).where(WatchTerm.term == "new"))
        assert s.scalar(select(ProjectPlatform.platform).where(ProjectPlatform.project_id == context.project_id)) == "X"


def test_api_safe_failure(client, settings, context):
    settings.rematch.refresh_project = Mock(side_effect=RuntimeError("postgresql://password"))
    r = client.post(f"/api/v1/projects/{context.project_id}/topics/{context.topic_id}/terms", json={"term": "new", "term_type": "KEYWORD"})
    assert r.status_code == 500 and "password" not in r.text and "postgresql" not in r.text


def test_batch_rematch_does_not_select_each_post(settings, context):
    with context.factory() as s, s.begin():
        s.add_all([SNSPost(project_id=context.project_id, platform="X", platform_post_id=str(i), source_type="MARKET", posted_at=T1, text="Batch", hashtags=[], raw_data={}) for i in range(1001)])
    statements = []
    engine = context.factory.kw["bind"]
    def capture(conn, cursor, statement, parameters, ctx, many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)
    event.listen(engine, "before_cursor_execute", capture)
    try:
        term = settings.create_term(context.project_id, context.topic_id, TermCreate(term="Batch", term_type="KEYWORD"))
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) < 30
    assert len([t for t in values(context, PostTerm) if t.term_id == term.term_id]) == 1001


@pytest.mark.parametrize("operation", ["term", "topic", "platform"])
def test_settings_lock_blocks_same_project_allows_other(context, operation):
    def factory():
        s = context.factory()
        event.listen(s, "after_begin", lambda session, transaction, conn: conn.exec_driver_sql("SET LOCAL lock_timeout = '250ms'"))
        return s
    service = SettingsService(factory)
    with context.factory() as s, s.begin():
        other = Project(name="Independent"); s.add(other); s.flush(); other_id = other.project_id
        s.add(ProjectPlatform(project_id=other_id, platform="X"))
    def action(project_id):
        if operation == "term": return service.create_term(project_id, context.topic_id, TermCreate(term="Lock", term_type="KEYWORD"))
        if operation == "topic": return service.patch_topic(project_id, context.topic_id, TopicPatch(is_active=False))
        return service.put_platforms(project_id, Platforms(platforms=["INSTAGRAM"]))
    try:
        with context.factory() as blocker, blocker.begin():
            blocker.execute(select(Project).where(Project.project_id == context.project_id).with_for_update())
            with ThreadPoolExecutor(max_workers=1) as executor:
                with pytest.raises(SettingsFailure) as exc:
                    executor.submit(action, context.project_id).result(timeout=5)
                assert exc.value.status == 500
                result = executor.submit(service.put_platforms, other_id, Platforms(platforms=["INSTAGRAM"])).result(timeout=5)
                assert result["platforms"] == ["INSTAGRAM"]
    finally:
        with context.factory() as s, s.begin(): s.execute(delete(Project).where(Project.project_id == other_id))


def test_import_waits_for_settings_refresh(context, tmp_path):
    entered, release, imported = Event(), Event(), Event()
    from app.services.rematch_service import RematchService
    class PausedRematch(RematchService):
        def refresh_project(self, session, project_id):
            entered.set()
            assert release.wait(5)
            super().refresh_project(session, project_id)
    service = SettingsService(context.factory, rematch=PausedRematch())
    path = tmp_path / "concurrent.csv"
    path.write_text(csv_text(D.TREND_POSTS, [row(D.TREND_POSTS, keyword="Concurrent")]), encoding="utf-8")
    identifier, started = context.service.start(context.project_id, D.TREND_POSTS, "concurrent.csv")
    def importing():
        result = context.service.run(identifier, started, context.project_id, D.TREND_POSTS, path)
        imported.set()
        return result
    with ThreadPoolExecutor(max_workers=2) as executor:
        setting = executor.submit(service.create_term, context.project_id, context.topic_id, TermCreate(term="Concurrent", term_type="KEYWORD"))
        try:
            assert entered.wait(3)
            importing_future = executor.submit(importing)
            assert not imported.wait(0.3)
        finally:
            release.set()
        term = setting.result(timeout=5)
        assert importing_future.result(timeout=5).status == "SUCCESS"
    assert any(t.term_id == term.term_id for t in values(context, PostTerm))
