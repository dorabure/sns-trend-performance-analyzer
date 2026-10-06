import pytest

from app.providers.base import CsvDatasetType as D, ProviderFileError
from app.providers.csv_provider import CSVProvider
from app.providers.csv_schema import SCHEMAS
from tests.providers.helpers import csv_text, row


@pytest.mark.parametrize("content,code", [("", "MISSING_HEADER"), ("\ufeff", "MISSING_HEADER"), ("\n", "MISSING_HEADER"),
    ("X,p1,dummy,2026-10-01T09:00:00Z\n", "MISSING_HEADER"), ("platform,platform\n", "DUPLICATE_HEADER"),
    ("platform, platform \n", "DUPLICATE_HEADER"), ("platform,\n", "EMPTY_HEADER")])
def test_bad_header(content, code):
    with pytest.raises(ProviderFileError) as error:
        CSVProvider().read_text(content, D.OWN_POSTS)
    assert error.value.error.code == code and error.value.error.field == "header"


@pytest.mark.parametrize("dataset", list(D))
def test_all_defined_headers_required_no_typo_fix(dataset):
    for header in SCHEMAS[dataset].headers:
        headers = list(SCHEMAS[dataset].headers)
        headers[headers.index(header)] = header + "_typo"
        with pytest.raises(ProviderFileError) as error:
            CSVProvider().read_text(csv_text(dataset, headers=headers), dataset)
        assert error.value.error.code == "MISSING_HEADER"
        assert header in error.value.error.message


@pytest.mark.parametrize("dataset,field", [(D.OWN_POSTS, f) for f in ("platform", "post_id", "account_name", "posted_at")] +
    [(D.ACCOUNT_DAILY, f) for f in ("platform", "account_name", "date")] +
    [(D.TREND_POSTS, f) for f in ("platform", "post_id", "posted_at")] +
    [(D.COMPETITOR_POSTS, f) for f in ("platform", "post_id", "account_name", "posted_at")])
def test_required_values(dataset, field):
    result = CSVProvider().read_text(csv_text(dataset, [row(dataset, **{field: "  "})]), dataset)
    assert result.invalid_rows == 1 and not result.records
    assert field in {e.field for e in result.errors}


@pytest.mark.parametrize("dataset,field", [(D.OWN_POSTS, f) for f in ("impressions", "reach", "views", "likes", "comments", "shares", "saves")] +
    [(D.ACCOUNT_DAILY, f) for f in ("followers", "following", "post_count")] +
    [(D.TREND_POSTS, f) for f in ("views", "likes", "comments", "shares")] +
    [(D.COMPETITOR_POSTS, f) for f in ("views", "likes", "comments", "shares", "followers")])
def test_negative_metrics_invalid_only_that_row(dataset, field):
    result = CSVProvider().read_text(csv_text(dataset, [row(dataset, **{field: "-1"}), row(dataset)]), dataset)
    assert (result.valid_rows, result.invalid_rows) == (1, 1)
    assert [(e.row_number, e.field, e.code) for e in result.errors] == [(2, field, "INVALID_INTEGER")]


@pytest.mark.parametrize("dataset,values,field", [(D.ACCOUNT_DAILY, {"date": "bad"}, "date"),
    (D.TREND_POSTS, {"posted_at": "2026-10-01T00:00:00"}, "posted_at"),
    (D.COMPETITOR_POSTS, {"media_type": "unknown"}, "media_type"),
    (D.OWN_POSTS, {"account_name": "a" * 101}, "account_name"),
    (D.OWN_POSTS, {"post_id": "p" * 256}, "post_id")])
def test_invalid_field_data(dataset, values, field):
    result = CSVProvider().read_text(csv_text(dataset, [row(dataset, **values)]), dataset)
    assert result.invalid_rows == 1 and result.errors[0].field == field


@pytest.mark.parametrize("tail", ['"unterminated', '"closed"invalid', 'too,many,cells', 'few,cells'])
def test_broken_structure_fatal_even_after_valid_row(tail):
    with pytest.raises(ProviderFileError) as error:
        CSVProvider().read_text(csv_text(D.OWN_POSTS) + tail, D.OWN_POSTS)
    assert error.value.error.code == "MALFORMED_CSV"


def test_file_missing_unreadable_and_encoding(tmp_path):
    with pytest.raises(ProviderFileError) as error:
        CSVProvider().read(tmp_path / "absent.csv", D.OWN_POSTS)
    assert error.value.error.code == "FILE_NOT_FOUND"
    with pytest.raises(ProviderFileError) as error:
        CSVProvider().read(tmp_path, D.OWN_POSTS)
    assert error.value.error.code == "FILE_UNREADABLE"
    file = tmp_path / "bad.csv"
    file.write_bytes(csv_text(D.OWN_POSTS).encode() + b"\xff")
    with pytest.raises(ProviderFileError) as error:
        CSVProvider().read(file, D.OWN_POSTS)
    assert error.value.error.code == "INVALID_ENCODING"


def test_sensitive_extra_column_is_fatal_without_exposing_value():
    content = csv_text(D.OWN_POSTS, [row(D.OWN_POSTS, access_token="dummy_secret")], list(SCHEMAS[D.OWN_POSTS].headers) + ["access_token"])
    with pytest.raises(ProviderFileError) as error:
        CSVProvider().read_text(content, D.OWN_POSTS)
    assert error.value.error.code == "SENSITIVE_HEADER"
    assert "dummy_secret" not in str(error.value)


def test_blank_cells_row_not_silently_ignored():
    result = CSVProvider().read_text(csv_text(D.OWN_POSTS, [dict.fromkeys(SCHEMAS[D.OWN_POSTS].headers, "")]), D.OWN_POSTS)
    assert result.total_rows == result.invalid_rows == 1 and len(result.errors) == 4
