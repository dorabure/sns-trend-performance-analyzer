from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select, update

from app.db.models import (AccountMetric, ImportHistory, PostMetric, PostTerm, PostTopic, Project,
                           SNSAccount, SNSPost)
from app.dto.normalized import NormalizedAccountMetric, ProviderResult
from app.providers.base import CsvDatasetType as D
from app.repositories.import_repository import ImportRepository
from app.services.import_service import ImportFailure, ImportService
from tests.imports.conftest import T1
from tests.providers.helpers import csv_text, row


def run_import(context, tmp_path, dataset=D.OWN_POSTS, rows=None, content=None, service=None):
    path = tmp_path / "input.csv"
    path.write_text(content if content is not None else csv_text(dataset, rows), encoding="utf-8", newline="")
    service = service or context.service
    identifier, started = service.start(context.project_id, dataset, "input.csv")
    return service.run(identifier, started, context.project_id, dataset, path)


def values(context, model):
    with context.factory() as session:
        return list(session.scalars(select(model)))


def history(context, result):
    with context.factory() as session:
        return session.get(ImportHistory, result.import_id)


@pytest.mark.parametrize("dataset,source,account", [(D.OWN_POSTS, "OWN", "own_id"),
    (D.TREND_POSTS, "MARKET", None), (D.COMPETITOR_POSTS, "COMPETITOR", "competitor_id")])
def test_post_import(context, tmp_path, dataset, source, account):
    data = row(dataset, account_name="competitor" if account == "competitor_id" else "dummy_demo",
               text="ChatGPT", hashtags="#ChatGPT", keyword="ChatGPT", likes="0", views="12")
    result = run_import(context, tmp_path, dataset, [data])
    assert (result.status, result.total_count, result.success_count, result.error_count) == ("SUCCESS", 1, 1, 0)
    post = values(context, SNSPost)[0]
    assert post.source_type == source
    assert post.account_id == (getattr(context, account) if account else None)
    assert post.author_name == (data["account_name"] if account else None)
    metric = values(context, PostMetric)[0]
    assert (metric.recorded_at, metric.likes, metric.views) == (T1, 0, 12)
    assert metric.raw_metrics["likes"] == 0
    assert metric.raw_metrics["impressions"] is None
    assert values(context, PostTerm)
    assert values(context, PostTopic)[0].match_score == 100
    assert history(context, result).status == "SUCCESS"
    assert len(values(context, SNSAccount)) == 3


def test_duplicate_update_snapshots_and_same_clock(context, tmp_path):
    run_import(context, tmp_path, rows=[row(D.OWN_POSTS, text="old", likes="1")])
    original = values(context, SNSPost)[0]
    later = ImportService(context.factory, now_provider=lambda: T1 + timedelta(hours=1))
    run_import(context, tmp_path, rows=[row(D.OWN_POSTS, text="new", likes="2")], service=later)
    updated = values(context, SNSPost)[0]
    assert updated.post_id == original.post_id and updated.created_at == original.created_at
    assert updated.updated_at > original.updated_at
    assert updated.text == "new"
    assert len(values(context, PostMetric)) == 2
    run_import(context, tmp_path, rows=[row(D.OWN_POSTS, likes="9")])
    metrics = values(context, PostMetric)
    assert len(metrics) == 2
    assert next(m.likes for m in metrics if m.recorded_at == T1) == 9


def test_duplicates_within_csv_counts_rows_and_rebuilds(context, tmp_path):
    result = run_import(context, tmp_path, rows=[row(D.OWN_POSTS, text="AI", likes="1"),
                                               row(D.OWN_POSTS, text="nothing", likes="2")])
    assert result.success_count == 2
    assert len(values(context, SNSPost)) == len(values(context, PostMetric)) == 1
    assert values(context, SNSPost)[0].text == "nothing"
    assert values(context, PostMetric)[0].likes == 2
    assert not values(context, PostTerm) and not values(context, PostTopic)


def test_same_natural_key_across_sources(context, tmp_path):
    run_import(context, tmp_path)
    original = values(context, SNSPost)[0]
    run_import(context, tmp_path, D.TREND_POSTS)
    market = values(context, SNSPost)[0]
    assert market.post_id == original.post_id and market.account_id is None and market.author_name is None
    run_import(context, tmp_path, D.COMPETITOR_POSTS, [row(D.COMPETITOR_POSTS, account_name="competitor")])
    post = values(context, SNSPost)[0]
    assert post.post_id == original.post_id and post.source_type == "COMPETITOR"
    assert post.account_id == context.competitor_id


@pytest.mark.parametrize("followers", ["", "NULL", "0", "42"])
def test_competitor_followers_original_date(context, tmp_path, followers):
    run_import(context, tmp_path, D.COMPETITOR_POSTS, [row(D.COMPETITOR_POSTS, account_name="competitor",
        followers=followers, posted_at="2026-10-02T00:30:00+09:00")])
    metrics = values(context, AccountMetric)
    if followers in ("", "NULL"):
        assert not metrics
    else:
        assert str(metrics[0].recorded_date) == "2026-10-02"
        assert metrics[0].followers == int(followers)


@pytest.mark.parametrize("times", [("2026-10-02T23:00:00+09:00", "2026-10-02T00:30:00+09:00"),
                                  ("2026-10-02T00:30:00+09:00", "2026-10-02T00:30:00+09:00")])
def test_competitor_followers_design_last_row_wins(context, tmp_path, times):
    with context.factory() as session, session.begin():
        session.add(AccountMetric(account_id=context.competitor_id, recorded_date=T1.date() - timedelta(days=1),
                                  followers=1, following=2, post_count=3, raw_metrics={"following": 2, "custom": "safe"}))
    result = run_import(context, tmp_path, D.COMPETITOR_POSTS, [row(D.COMPETITOR_POSTS, account_name="competitor",
        post_id=f"c{i}", followers=str(value), posted_at=when) for i, (value, when) in enumerate(zip([10, 20], times))])
    assert result.status == "SUCCESS"
    metric = values(context, AccountMetric)[0]
    assert (metric.followers, metric.following, metric.post_count) == (20, 2, 3)
    assert metric.raw_metrics == {"following": 2, "followers": 20, "custom": "safe"}


@pytest.mark.parametrize("followers", ["", "NULL", "0", "99"])
def test_account_daily_upsert_replaces_nullable_metrics(context, tmp_path, followers):
    run_import(context, tmp_path, D.ACCOUNT_DAILY, [row(D.ACCOUNT_DAILY, followers="3", following="4", post_count="5")])
    original = values(context, AccountMetric)[0]
    result = run_import(context, tmp_path, D.ACCOUNT_DAILY, [row(D.ACCOUNT_DAILY, followers=followers)])
    metrics = values(context, AccountMetric)
    assert len(metrics) == 1 and metrics[0].account_metric_id == original.account_metric_id
    assert metrics[0].followers == (None if followers in ("", "NULL") else int(followers))
    assert metrics[0].following is None and metrics[0].post_count is None
    assert metrics[0].raw_metrics["followers"] == followers
    assert result.success_count == 1
    assert not values(context, SNSPost)


def test_daily_duplicate_within_file(context, tmp_path):
    result = run_import(context, tmp_path, D.ACCOUNT_DAILY, [row(D.ACCOUNT_DAILY, followers="1"), row(D.ACCOUNT_DAILY, followers="2")])
    assert result.success_count == 2
    assert len(values(context, AccountMetric)) == 1
    assert values(context, AccountMetric)[0].followers == 2


def test_mixed_ten_rows_counts_errors_by_source_row(context, tmp_path):
    rows = [row(D.OWN_POSTS, post_id=f"p{i}") for i in range(10)]
    rows[0].update(likes="bad", comments="bad", shares="bad")
    rows[1].update(posted_at="bad")
    rows[2].update(account_name="unknown")
    result = run_import(context, tmp_path, rows=rows)
    assert (result.status, result.total_count, result.success_count, result.error_count) == ("PARTIAL_ERROR", 10, 7, 3)
    assert len(result.errors) == 5 and len(values(context, SNSPost)) == 7
    assert history(context, result).error_detail == result.errors
    assert {e["row"] for e in result.errors} == {2, 3, 4}


@pytest.mark.parametrize("rows", [[row(D.OWN_POSTS, likes="bad")], [row(D.OWN_POSTS, account_name="unknown")]])
def test_all_invalid_is_partial(context, tmp_path, rows):
    result = run_import(context, tmp_path, rows=rows)
    assert (result.status, result.total_count, result.success_count, result.error_count) == ("PARTIAL_ERROR", 1, 0, 1)
    assert not values(context, SNSPost)
    assert history(context, result).status == "PARTIAL_ERROR"


def test_header_only_success(context, tmp_path):
    result = run_import(context, tmp_path, rows=[])
    assert result.status == "SUCCESS" and result.total_count == 0


@pytest.mark.parametrize("dataset,account,code", [(D.OWN_POSTS, "competitor", "ACCOUNT_ROLE_MISMATCH"),
    (D.COMPETITOR_POSTS, "dummy_demo", "ACCOUNT_ROLE_MISMATCH"), (D.COMPETITOR_POSTS, "inactive", "ACCOUNT_NOT_FOUND"),
    (D.OWN_POSTS, "unknown", "ACCOUNT_NOT_FOUND"), (D.OWN_POSTS, "Dummy_demo", "ACCOUNT_NOT_FOUND"),
    (D.ACCOUNT_DAILY, "competitor", "ACCOUNT_ROLE_MISMATCH")])
def test_account_resolution(context, tmp_path, dataset, account, code):
    result = run_import(context, tmp_path, dataset, [row(dataset, account_name=account)])
    assert result.error_count == 1 and result.errors[0]["code"] == code
    assert not values(context, SNSPost) and not values(context, AccountMetric)


def test_platform_disabled_skips_row(context, tmp_path):
    result = run_import(context, tmp_path, rows=[row(D.OWN_POSTS, platform="INSTAGRAM"), row(D.OWN_POSTS)])
    assert result.success_count == result.error_count == 1
    assert result.errors[0]["code"] == "PLATFORM_NOT_ENABLED"


@pytest.mark.parametrize("inactive", [False, True])
def test_project_validation_precedes_provider(context, tmp_path, inactive):
    if inactive:
        with context.factory() as session, session.begin():
            session.execute(update(Project).where(Project.project_id == context.project_id).values(is_active=False))
    identifier = context.project_id if inactive else uuid4()
    with pytest.raises(ImportFailure) as error:
        context.service.start(identifier, D.OWN_POSTS, "sample.csv")
    assert error.value.status_code == (409 if inactive else 404)
    assert not values(context, ImportHistory)


@pytest.mark.parametrize("content,code", [("broken\n", "MISSING_HEADER"), ("", "MISSING_HEADER"),
    (csv_text(D.OWN_POSTS) + '"unterminated', "MALFORMED_CSV"),
    (csv_text(D.OWN_POSTS, headers=list(row(D.OWN_POSTS)) + ["api_token"]), "SENSITIVE_HEADER")])
def test_file_fatal_preserves_failed_history(context, tmp_path, content, code):
    with pytest.raises(ImportFailure) as error:
        run_import(context, tmp_path, content=content)
    result = error.value.result
    assert result.status == "FAILED" and result.total_count == result.success_count == 0
    assert result.errors[0]["code"] == code
    assert history(context, result).status == "FAILED"
    assert not values(context, SNSPost)


@pytest.mark.parametrize("kind", ["repository", "history", "integrity"])
def test_business_rollback_and_durable_audit(context, tmp_path, monkeypatch, kind):
    repository = ImportRepository()
    service = ImportService(context.factory, repository=repository, now_provider=lambda: T1)
    writes = 0
    if kind in ("repository", "integrity"):
        original = repository.save_post
        def broken(*args):
            nonlocal writes
            result = original(*args)
            writes += 1
            if writes == 2:
                if kind == "integrity":
                    args[0].execute(update(AccountMetric).values(followers=-1))
                raise RuntimeError("password=secret SQL private traceback")
            return result
        monkeypatch.setattr(repository, "save_post", broken)
    else:
        original = service.finish_history
        def broken(session, result):
            original(session, result)
            if result.status != "FAILED":
                raise RuntimeError("history completion failure")
        monkeypatch.setattr(service, "finish_history", broken)
    with pytest.raises(ImportFailure) as error:
        run_import(context, tmp_path, D.COMPETITOR_POSTS, [row(D.COMPETITOR_POSTS, account_name="competitor",
            post_id=f"c{i}", text="AI", followers="12") for i in range(3)], service=service)
    result = error.value.result
    assert error.value.status_code == 500
    assert (result.status, result.total_count, result.success_count) == ("FAILED", 3, 0)
    for model in (SNSPost, PostMetric, AccountMetric, PostTerm, PostTopic):
        assert not values(context, model)
    assert history(context, result).status == "FAILED"
    assert "secret" not in str(result) and "traceback" not in str(result)


def test_processing_history_visible_before_provider(context, tmp_path):
    class InspectProvider:
        def read(self, path, dataset):
            histories = values(context, ImportHistory)
            assert len(histories) == 1 and histories[0].status == "PROCESSING"
            from app.providers.csv_provider import CSVProvider
            return CSVProvider().read(path, dataset)
    result = run_import(context, tmp_path, service=ImportService(context.factory, provider=InspectProvider()))
    assert history(context, result).status == "SUCCESS"


def test_commit_failure_rolls_back_business_and_finishes_audit(context, tmp_path):
    def factory():
        session = context.factory()
        def before_commit(current):
            status = current.scalar(select(ImportHistory.status).where(ImportHistory.project_id == context.project_id))
            if status == "SUCCESS":
                raise RuntimeError("simulated commit failure secret")
        event.listen(session, "before_commit", before_commit)
        return session
    with pytest.raises(ImportFailure) as error:
        run_import(context, tmp_path, service=ImportService(factory))
    assert error.value.status_code == 500
    assert not values(context, SNSPost) and not values(context, PostMetric)
    assert history(context, error.value.result).status == "FAILED"


def test_rollback_restores_existing_post_and_matches(context, tmp_path, monkeypatch):
    run_import(context, tmp_path, rows=[row(D.OWN_POSTS, text="AI", likes="1")])
    original = values(context, SNSPost)[0]
    original_save = context.service.repository.save_post
    def broken(*args):
        original_save(*args)
        raise RuntimeError("fail after existing post update")
    monkeypatch.setattr(context.service.repository, "save_post", broken)
    with pytest.raises(ImportFailure):
        run_import(context, tmp_path, rows=[row(D.OWN_POSTS, text="different", likes="99")])
    restored = values(context, SNSPost)[0]
    assert (restored.post_id, restored.text, restored.updated_at) == (original.post_id, "AI", original.updated_at)
    assert values(context, PostMetric)[0].likes == 1
    assert values(context, PostTerm)[0].term_id == context.terms["AI"]


def test_inactive_own_account(context, tmp_path):
    with context.factory() as session, session.begin():
        session.execute(update(SNSAccount).where(SNSAccount.account_id == context.own_id).values(is_active=False))
    result = run_import(context, tmp_path)
    assert result.errors[0]["code"] == "ACCOUNT_NOT_FOUND" and result.error_count == 1


def test_wrong_source_contract_is_fatal(context, tmp_path):
    from dataclasses import replace
    from app.dto.normalized import SourceType
    from app.providers.csv_provider import CSVProvider
    class BadProvider:
        def read(self, path, dataset):
            result = CSVProvider().read(path, dataset)
            return ProviderResult([replace(result.records[0], source_type=SourceType.MARKET)], [], 1)
    with pytest.raises(ImportFailure) as error:
        run_import(context, tmp_path, service=ImportService(context.factory, provider=BadProvider()))
    assert history(context, error.value.result).status == "FAILED" and not values(context, SNSPost)


def test_clock_requires_timezone(context):
    from datetime import datetime
    service = ImportService(context.factory, now_provider=lambda: datetime(2026, 10, 3))
    with pytest.raises(ImportFailure) as error:
        service.start(context.project_id, D.OWN_POSTS, "input.csv")
    assert error.value.status_code == 500 and not values(context, ImportHistory)


def test_success_history_and_data_visible_together(context, tmp_path, monkeypatch):
    original = context.service.finish_history
    def check(session, result):
        original(session, result)
        # Independent connection sees neither uncommitted posts nor final history.
        assert not values(context, SNSPost)
        assert history(context, result).status == "PROCESSING"
        assert session.scalar(select(func.count()).select_from(SNSPost)) == 1
    monkeypatch.setattr(context.service, "finish_history", check)
    result = run_import(context, tmp_path)
    assert len(values(context, SNSPost)) == 1 and history(context, result).status == "SUCCESS"


@pytest.mark.parametrize("wrong", [object(), NormalizedAccountMetric("X", "dummy_demo", T1.date())])
def test_dto_contract_is_fatal(context, tmp_path, wrong):
    class BadProvider:
        def read(self, path, dataset):
            return ProviderResult([wrong], [], 1)
    with pytest.raises(ImportFailure) as error:
        run_import(context, tmp_path, service=ImportService(context.factory, provider=BadProvider()))
    assert error.value.status_code == 500
    assert history(context, error.value.result).status == "FAILED"


@pytest.mark.parametrize("topic_method", ["MANUAL", "AI"])
def test_matching_inactive_and_rebuild_preserves_manual_ai(context, tmp_path, topic_method):
    run_import(context, tmp_path, rows=[row(D.OWN_POSTS, text="AI inactive disabled", hashtags="#ChatGPT")])
    post_id = values(context, SNSPost)[0].post_id
    initial = {t.term_id for t in values(context, PostTerm)}
    assert initial == {context.terms["AI"], context.terms["#ChatGPT"]}
    with context.factory() as session, session.begin():
        session.add(PostTerm(post_id=post_id, term_id=context.terms["ChatGPT"], match_method="MANUAL", match_score=77))
        session.add(PostTerm(post_id=post_id, term_id=context.terms["生成AI"], match_method="AI", match_score=55))
        session.execute(update(PostTopic).where(PostTopic.post_id == post_id).values(match_type=topic_method, match_score=66))
    run_import(context, tmp_path, rows=[row(D.OWN_POSTS, text="ChatGPT", hashtags="#生成AI")])
    terms = {t.term_id: t for t in values(context, PostTerm)}
    assert context.terms["#ChatGPT"] not in terms and context.terms["AI"] not in terms
    assert terms[context.terms["ChatGPT"]].match_method == "MANUAL" and terms[context.terms["ChatGPT"]].match_score == 77
    assert terms[context.terms["生成AI"]].match_method == "AI" and terms[context.terms["生成AI"]].match_score == 55
    assert terms[context.terms["#生成AI"]].match_method == "EXACT"
    assert values(context, PostTopic)[0].match_type == topic_method and values(context, PostTopic)[0].match_score == 66


def test_preserved_term_keeps_parent_topic_without_new_match(context, tmp_path):
    run_import(context, tmp_path)
    post_id = values(context, SNSPost)[0].post_id
    with context.factory() as session, session.begin():
        session.add(PostTerm(post_id=post_id, term_id=context.terms["AI"], match_method="AI", match_score=30))
    run_import(context, tmp_path, rows=[row(D.OWN_POSTS, text="nothing")])
    assert len(values(context, PostTerm)) == len(values(context, PostTopic)) == 1
    assert values(context, PostTopic)[0].topic_id == context.topic_id
