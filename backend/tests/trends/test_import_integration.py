from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from sqlalchemy import delete, event, select

from app.db.models import ImportHistory, PostMetric, PostTerm, PostTopic, Project, ProjectPlatform, SNSPost, TrendDaily
from app.providers.base import CsvDatasetType as D
from app.services.import_service import ImportFailure, ImportService
from app.services.trend_service import TrendService
from tests.imports.test_pipeline import history, run_import, values
from tests.providers.helpers import csv_text, row
from tests.trends.test_trend_service import semantic_rows


def test_market_import_api_commits_trend_and_history(client, context):
    response = client.post(f"/api/v1/projects/{context.project_id}/imports",
        data={"import_type": "TREND_POSTS"}, files={"file": ("trend.csv",
            csv_text(D.TREND_POSTS, [row(D.TREND_POSTS, keyword="AI", likes="10")]).encode(), "text/csv")})
    assert response.status_code == 200 and response.json()["status"] == "SUCCESS"
    assert len(values(context, TrendDaily)) == 6
    topic = next(t for t in values(context, TrendDaily) if t.term_id is None)
    assert topic.post_count == 1 and topic.engagement_count == 10
    assert values(context, ImportHistory)[0].status == "SUCCESS"


@pytest.mark.parametrize("dataset", [D.OWN_POSTS, D.COMPETITOR_POSTS])
def test_market_source_reclassification_removes_trend(context, tmp_path, dataset):
    run_import(context, tmp_path, D.TREND_POSTS, [row(D.TREND_POSTS, keyword="AI")])
    original = values(context, SNSPost)[0].post_id
    assert values(context, TrendDaily)
    run_import(context, tmp_path, dataset, [row(dataset, account_name="competitor" if dataset == D.COMPETITOR_POSTS else "dummy_demo")])
    assert values(context, SNSPost)[0].post_id == original and not values(context, TrendDaily)
    run_import(context, tmp_path, D.TREND_POSTS, [row(D.TREND_POSTS, keyword="AI")])
    assert values(context, SNSPost)[0].post_id == original and values(context, TrendDaily)


def test_account_daily_never_rebuilds(context, tmp_path):
    trend = Mock()
    service = ImportService(context.factory, trend_service=trend)
    result = run_import(context, tmp_path, D.ACCOUNT_DAILY, service=service)
    assert result.status == "SUCCESS"
    trend.rebuild_project.assert_not_called()


@pytest.mark.parametrize("dataset", [D.OWN_POSTS, D.TREND_POSTS, D.COMPETITOR_POSTS])
def test_post_import_rebuilds_once_after_all_rows(context, tmp_path, dataset):
    observations = []
    class SpyTrend(TrendService):
        def rebuild_project(self, session, project_id):
            assert project_id == context.project_id
            assert len(list(session.scalars(select(SNSPost)))) == 2
            assert session.scalar(select(ImportHistory.status)) == "PROCESSING"
            observations.append(session)
            return super().rebuild_project(session, project_id)
    service = ImportService(context.factory, trend_service=SpyTrend())
    result = run_import(context, tmp_path, dataset, [row(dataset, post_id=f"p{i}",
        account_name="competitor" if dataset == D.COMPETITOR_POSTS else "dummy_demo") for i in range(2)], service=service)
    assert result.status == "SUCCESS" and len(observations) == 1


def test_partial_import_rebuilds_only_valid_rows(context, tmp_path):
    result = run_import(context, tmp_path, D.TREND_POSTS, [row(D.TREND_POSTS, post_id="valid", keyword="AI", likes="10"),
                                                        row(D.TREND_POSTS, post_id="bad", likes="bad")])
    assert (result.status, result.success_count, result.error_count) == ("PARTIAL_ERROR", 1, 1)
    assert next(t for t in values(context, TrendDaily) if t.term_id is None).post_count == 1


@pytest.mark.parametrize("initial", [False, True])
def test_trend_failure_rolls_back_all_import_changes_and_preserves_audit(context, tmp_path, initial):
    if initial:
        run_import(context, tmp_path, D.TREND_POSTS, [row(D.TREND_POSTS, keyword="AI", text="AI", likes="10")])
    before_trends = values(context, TrendDaily)
    before_ids = {t.trend_daily_id for t in before_trends}
    before_posts = [(p.post_id, p.text) for p in values(context, SNSPost)]
    before_metrics = [(p.post_metric_id, p.likes) for p in values(context, PostMetric)]
    before_terms = [(p.post_id, p.term_id, p.match_method) for p in values(context, PostTerm)]
    before_topics = [(p.post_id, p.topic_id, p.match_type) for p in values(context, PostTopic)]
    class BrokenTrend(TrendService):
        def rebuild_project(self, session, project_id):
            super().rebuild_project(session, project_id)
            raise RuntimeError("private SQL password=secret")
    with pytest.raises(ImportFailure) as error:
        run_import(context, tmp_path, D.TREND_POSTS, [row(D.TREND_POSTS, keyword="ChatGPT", text="changed", likes="999"),
            row(D.TREND_POSTS, post_id="new", keyword="AI")], service=ImportService(context.factory, trend_service=BrokenTrend()))
    assert error.value.status_code == 500 and error.value.result.success_count == 0
    assert history(context, error.value.result).status == "FAILED"
    assert "secret" not in str(error.value.result)
    after = values(context, TrendDaily)
    assert {t.trend_daily_id for t in after} == before_ids
    assert semantic_rows(after) == semantic_rows(before_trends)
    assert [(p.post_id, p.text) for p in values(context, SNSPost)] == before_posts
    assert [(p.post_metric_id, p.likes) for p in values(context, PostMetric)] == before_metrics
    assert [(p.post_id, p.term_id, p.match_method) for p in values(context, PostTerm)] == before_terms
    assert [(p.post_id, p.topic_id, p.match_type) for p in values(context, PostTopic)] == before_topics


def test_trend_and_final_history_share_commit(context, tmp_path, monkeypatch):
    original = context.service.finish_history
    def check(session, result):
        original(session, result)
        assert list(session.scalars(select(TrendDaily)))
        assert not values(context, TrendDaily)
        assert history(context, result).status == "PROCESSING"
    monkeypatch.setattr(context.service, "finish_history", check)
    result = run_import(context, tmp_path, D.TREND_POSTS, [row(D.TREND_POSTS, keyword="AI")])
    assert result.status == "SUCCESS" and values(context, TrendDaily)


def test_post_import_exclusive_lock_is_project_scoped(context, tmp_path):
    path = tmp_path / "trend.csv"
    path.write_text(csv_text(D.TREND_POSTS, [row(D.TREND_POSTS, keyword="AI")]), encoding="utf-8")
    def factory():
        session = context.factory()
        def timeout(current, transaction, connection):
            connection.exec_driver_sql("SET LOCAL lock_timeout = '250ms'")
        event.listen(session, "after_begin", timeout)
        return session
    service = ImportService(factory)
    identifier, started = service.start(context.project_id, D.TREND_POSTS, "trend.csv")
    with context.factory() as session, session.begin():
        other = Project(name="Independent project")
        session.add(other)
        session.flush()
        session.add(ProjectPlatform(project_id=other.project_id, platform="X"))
    other_id, other_start = service.start(other.project_id, D.TREND_POSTS, "trend.csv")
    try:
        with context.factory() as blocker, blocker.begin():
            # A shared lock permits Phase 4's old shared behavior; Phase 5 must block.
            blocker.execute(select(Project).where(Project.project_id == context.project_id).with_for_update(read=True))
            with ThreadPoolExecutor(max_workers=1) as executor:
                failed = executor.submit(service.run, identifier, started, context.project_id, D.TREND_POSTS, path)
                with pytest.raises(ImportFailure) as error:
                    failed.result(timeout=5)
                assert error.value.status_code == 500
                assert history(context, error.value.result).status == "FAILED"
                # The other project succeeds while the first project is still locked.
                succeeded = executor.submit(service.run, other_id, other_start, other.project_id, D.TREND_POSTS, path).result(timeout=5)
                assert succeeded.status == "SUCCESS"
        with context.factory() as session:
            assert not list(session.scalars(select(SNSPost).where(SNSPost.project_id == context.project_id)))
    finally:
        with context.factory() as session, session.begin():
            session.execute(delete(Project).where(Project.project_id == other.project_id))


def test_daily_keeps_shared_lock(context, tmp_path):
    identifier, started = context.service.start(context.project_id, D.ACCOUNT_DAILY, "account.csv")
    path = tmp_path / "account.csv"
    path.write_text(csv_text(D.ACCOUNT_DAILY), encoding="utf-8")
    with context.factory() as blocker, blocker.begin():
        blocker.execute(select(Project).where(Project.project_id == context.project_id).with_for_update(read=True))
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = executor.submit(context.service.run, identifier, started, context.project_id, D.ACCOUNT_DAILY, path).result(timeout=5)
            assert result.status == "SUCCESS"
