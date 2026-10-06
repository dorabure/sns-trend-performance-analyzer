from datetime import date, timedelta
from pathlib import Path

import pytest

from app.dto.normalized import NormalizedAccountMetric, NormalizedCompetitorData, NormalizedPost, NormalizedTrendData
from app.providers.base import CsvDatasetType as D, DataProvider
from app.providers.csv_provider import CSVProvider
from app.providers.csv_schema import SCHEMAS
from tests.providers.helpers import csv_text, row


@pytest.mark.parametrize("dataset,kind", [(D.OWN_POSTS, NormalizedPost), (D.ACCOUNT_DAILY, NormalizedAccountMetric),
    (D.TREND_POSTS, NormalizedTrendData), (D.COMPETITOR_POSTS, NormalizedCompetitorData)])
def test_four_files_and_explicit_dataset(dataset, kind, tmp_path):
    file = tmp_path / "arbitrary_name.csv"
    file.write_text(csv_text(dataset), encoding="utf-8")
    provider: DataProvider = CSVProvider()
    result = provider.read(file, dataset)
    assert (result.total_rows, result.valid_rows, result.invalid_rows, result.errors) == (1, 1, 0, [])
    assert isinstance(result.records[0], kind)


def test_own_posts():
    rows = [row(D.OWN_POSTS, platform="Twitter", text=" テスト 😀 https://example.test ", media_type="photo", hashtags="#生成AI;#ChatGPT;#生成AI", impressions="100", reach="NULL", views="0", likes="1", comments="2", shares="3", saves="4"),
            row(D.OWN_POSTS, platform="Instagram", post_id="p2", media_type="REEL")]
    result = CSVProvider().read_text(csv_text(D.OWN_POSTS, rows), D.OWN_POSTS)
    assert result.valid_rows == 2
    post, other = result.records
    assert post.source_type == other.source_type == "OWN"
    assert post.platform == "X" and other.platform == "INSTAGRAM"
    assert post.posted_at.utcoffset() == timedelta(hours=9)
    assert (post.impressions, post.reach, post.views, post.likes, post.comments, post.shares, post.saves) == (100, None, 0, 1, 2, 3, 4)
    assert post.media_type == "IMAGE" and other.media_type == "VIDEO"
    assert post.hashtags == ["#生成AI", "#ChatGPT"]
    assert post.text == "テスト 😀 https://example.test"


@pytest.mark.parametrize("followers,expected", [("NULL", None), ("0", 0), ("125", 125)])
def test_account_daily(followers, expected):
    result = CSVProvider().read_text(csv_text(D.ACCOUNT_DAILY, [row(D.ACCOUNT_DAILY, followers=followers, following="2", post_count="0")]), D.ACCOUNT_DAILY)
    record = result.records[0]
    assert record.recorded_date == date(2026, 10, 1)
    assert (record.followers, record.following, record.post_count) == (expected, 2, 0)


@pytest.mark.parametrize("keyword,expected", [(" ChatGPT ", ["ChatGPT"]), ("", []), ("AI, Gemini", ["AI, Gemini"])])
def test_market_post_has_no_account(keyword, expected):
    result = CSVProvider().read_text(csv_text(D.TREND_POSTS, [row(D.TREND_POSTS, keyword=keyword, views="NULL", likes="0", comments="3", shares="4", hashtags="#生成AI")]), D.TREND_POSTS)
    record = result.records[0]
    assert record.post.source_type == "MARKET" and record.post.account_name is None
    assert record.keywords == record.post.keywords == expected
    assert (record.post.views, record.post.likes, record.post.comments, record.post.shares) == (None, 0, 3, 4)
    assert record.post.hashtags == ["#生成AI"]


@pytest.mark.parametrize("followers,expected", [("", None), ("null", None), ("0", 0), ("100", 100)])
def test_competitor_followers_separate_from_post_metrics(followers, expected):
    result = CSVProvider().read_text(csv_text(D.COMPETITOR_POSTS, [row(D.COMPETITOR_POSTS, followers=followers, media_type="ALBUM", views="25")]), D.COMPETITOR_POSTS)
    record = result.records[0]
    assert record.post.source_type == "COMPETITOR" and record.followers == expected
    assert record.post.media_type == "CAROUSEL" and record.post.views == 25
    assert not hasattr(record.post, "followers")


@pytest.mark.parametrize("dataset", list(D))
def test_bom_trim_reordered_headers_and_extra_data(dataset, tmp_path):
    headers = [" " + name + " " for name in reversed(SCHEMAS[dataset].headers)] + ["extra_note"]
    values = row(dataset)
    values["extra_note"] = " original 😀 "
    values["platform"] = " instagram "
    file = tmp_path / "test.csv"
    file.write_text(csv_text(dataset, [values], headers), encoding="utf-8-sig")
    record = CSVProvider().read(file, dataset).records[0]
    dto = record.post if hasattr(record, "post") else record
    raw = dto.raw_data if hasattr(dto, "raw_data") else dto.raw_metrics
    assert dto.platform == "INSTAGRAM" and raw["extra_note"] == " original 😀 "


def test_mixed_valid_invalid_counts_one_row_with_multiple_errors():
    rows = [row(D.OWN_POSTS, post_id=f"p{i}") for i in range(10)]
    rows[2].update(post_id="", account_name="", likes="-1")
    rows[5]["platform"] = "IG"
    rows[8]["posted_at"] = "invalid"
    result = CSVProvider().read_text(csv_text(D.OWN_POSTS, rows), D.OWN_POSTS)
    assert (len(result.records), result.total_rows, result.valid_rows, result.invalid_rows) == (7, 10, 7, 3)
    assert {e.row_number for e in result.errors} == {4, 7, 10}
    assert len(result.errors) == 5
    assert {e.field for e in result.errors if e.row_number == 4} == {"post_id", "account_name", "likes"}


def test_multiline_quoted_text_and_physical_row_numbers():
    rows = [row(D.OWN_POSTS, text='first,"quoted"\nsecond 😀'), row(D.OWN_POSTS, post_id="", text="ok")]
    result = CSVProvider().read_text(csv_text(D.OWN_POSTS, rows), D.OWN_POSTS)
    assert result.records[0].text == 'first,"quoted"\nsecond 😀'
    assert result.records[0].row_number == 2
    assert result.errors[0].row_number == 4


@pytest.mark.parametrize("dataset", list(D))
def test_header_only_and_blank_lines(dataset):
    result = CSVProvider().read_text(csv_text(dataset, []) + "\r\n", dataset)
    assert result.total_rows == result.valid_rows == result.invalid_rows == 0


def test_dummy_fixture_files():
    root = Path(__file__).parents[1] / "fixtures" / "csv"
    for dataset in D:
        result = CSVProvider().read(root / f"{dataset.value.lower()}.csv", dataset)
        assert result.valid_rows == 1 and not result.errors
