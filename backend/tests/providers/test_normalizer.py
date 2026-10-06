import os
import subprocess
import sys
from datetime import date, timedelta

import pytest

from app.dto.normalized import SourceType
from app.normalizers.common import (
    FieldNormalizationError, Normalizer, normalize_date, normalize_datetime,
    normalize_hashtags, normalize_integer, normalize_keywords, normalize_media_type,
    normalize_platform, safe_raw,
)
from app.providers.base import RowValidationError


@pytest.mark.parametrize("value,expected", [("X", "X"), ("x", "X"), ("Twitter", "X"), ("twitter", "X"),
    (" Instagram ", "INSTAGRAM"), ("instagram", "INSTAGRAM"), ("INSTAGRAM", "INSTAGRAM")])
def test_platform(value, expected):
    assert normalize_platform(value) == expected


@pytest.mark.parametrize("value", [None, "", "IG", "ALL", "Threads"])
def test_unknown_platform(value):
    with pytest.raises(FieldNormalizationError, match="Platform"):
        normalize_platform(value)


@pytest.mark.parametrize("value,expected", [("TEXT", "TEXT"), ("image", "IMAGE"), ("PHOTO", "IMAGE"),
    ("VIDEO", "VIDEO"), ("reel", "VIDEO"), ("CAROUSEL", "CAROUSEL"), ("Album", "CAROUSEL"),
    ("OTHER", "OTHER"), ("", None), (None, None), ("NULL", None)])
def test_media(value, expected):
    assert normalize_media_type(value) == expected


def test_unknown_media_does_not_become_other():
    with pytest.raises(FieldNormalizationError):
        normalize_media_type("livestream")


@pytest.mark.parametrize("value,expected", [(None, None), ("", None), (" NULL ", None), ("null", None),
    ("0", 0), (" 123 ", 123), ("00042", 42), (str(2**63 - 1), 2**63 - 1)])
def test_numeric_null_zero_and_boundary(value, expected):
    assert normalize_integer(value) == expected


@pytest.mark.parametrize("value", ["-1", "1.5", "1e3", "1,000", "abc", "+1", "１２", str(2**63), "9" * 5000])
def test_bad_integer(value):
    with pytest.raises(FieldNormalizationError):
        normalize_integer(value)


@pytest.mark.parametrize("value,offset", [("2026-10-01T09:30:00Z", timedelta(0)),
    (" 2026-10-01T18:30:00+09:00 ", timedelta(hours=9)), ("2026-10-01T09:30:00.123456-04:00", timedelta(hours=-4))])
def test_datetime_keeps_timezone(value, offset):
    assert normalize_datetime(value).utcoffset() == offset


@pytest.mark.parametrize("value", ["", "bad", "2026-10-01", "2026-10-01T18:30:00", "2026-02-30T00:00:00Z", "2026-10-01T18:30:00+09:99", "2026-10-01T24:00:00Z"])
def test_datetime_rejects_missing_zone_or_invalid(value):
    with pytest.raises(FieldNormalizationError):
        normalize_datetime(value)


def test_date_and_keyword():
    assert normalize_date(" 2026-10-01 ") == date(2026, 10, 1)
    assert normalize_keywords("  ChatGPT ＡI 😀  ") == ["ChatGPT ＡI 😀"]
    assert normalize_keywords("") == []


@pytest.mark.parametrize("value", ["2026/10/01", "20261001", "2026-02-30", "2026-10-01T00:00:00Z"])
def test_bad_date(value):
    with pytest.raises(FieldNormalizationError):
        normalize_date(value)


def test_hashtag_order_and_case_preserved():
    assert normalize_hashtags(" #生成AI ; ChatGPT;;#生成AI; #chatgpt ") == ["#生成AI", "#ChatGPT", "#chatgpt"]
    assert normalize_hashtags("") == []


@pytest.mark.parametrize("value", ["#", "#a #b", "#a,#b", "##abc"])
def test_hashtag_ambiguous_format(value):
    with pytest.raises(FieldNormalizationError):
        normalize_hashtags(value)


def test_common_contract_without_csv_names():
    data = {"platform": "Twitter", "platform_post_id": " canonical ", "account_name": " dummy ",
            "posted_at": "2026-10-01T09:30:00Z", "likes": "0", "text": "  Ａ 😀 https://example.test\n内容  "}
    post = Normalizer().normalize_post(data, SourceType.OWN)
    assert post.platform_post_id == "canonical" and post.likes == 0
    assert post.text == "Ａ 😀 https://example.test\n内容"
    assert post.raw_data == data and post.raw_data is not data
    with pytest.raises(RowValidationError) as error:
        Normalizer().normalize_post({}, SourceType.OWN, 12)
    assert {e.field for e in error.value.errors} == {"platform", "platform_post_id", "account_name", "posted_at"}
    assert {e.row_number for e in error.value.errors} == {12}


@pytest.mark.parametrize("name", ["access_token", "API-Key", "client_secret", "password", "Authorization"])
def test_credentials_are_not_raw_data(name):
    with pytest.raises(FieldNormalizationError) as error:
        safe_raw({name: "dummy_sensitive_value"})
    assert "dummy_sensitive_value" not in str(error.value)


def test_provider_import_does_not_load_database_or_need_settings():
    environment = {key: value for key, value in os.environ.items() if not key.startswith("POSTGRES_")}
    code = "from app.providers.csv_provider import CSVProvider; import sys; assert not any(k.startswith('app.db') for k in sys.modules)"
    completed = subprocess.run([sys.executable, "-c", code], env=environment, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
