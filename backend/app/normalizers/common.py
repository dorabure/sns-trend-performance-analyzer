import re
from datetime import date, datetime
from typing import Callable, Mapping, TypeVar

from app.dto.normalized import (
    MediaType, NormalizedAccountMetric, NormalizedCompetitorData, NormalizedPost,
    NormalizedTrendData, Platform, SourceType, ValidationError,
)
from app.providers.base import RowValidationError

POST_METRICS = ("impressions", "reach", "views", "likes", "comments", "shares", "saves")
ACCOUNT_METRICS = ("followers", "following", "post_count")
MAX_BIGINT = 2**63 - 1


class FieldNormalizationError(ValueError):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


def optional_text(value: str | None) -> str | None:
    return value.strip() or None if value is not None else None


def required_text(value: str | None, limit: int) -> str:
    result = optional_text(value)
    if result is None:
        raise FieldNormalizationError("REQUIRED_VALUE", "A non-empty value is required")
    if len(result) > limit:
        raise FieldNormalizationError("VALUE_TOO_LONG", f"Value must not exceed {limit} characters")
    return result


def normalize_platform(value: str | None) -> Platform:
    aliases = {"x": Platform.X, "twitter": Platform.X, "instagram": Platform.INSTAGRAM}
    try:
        return aliases[(value or "").strip().lower()]
    except KeyError:
        raise FieldNormalizationError("INVALID_PLATFORM", "Platform must be X/Twitter or Instagram") from None


def normalize_media_type(value: str | None) -> MediaType | None:
    name = (value or "").strip().upper()
    if name in ("", "NULL"):
        return None
    name = {"PHOTO": "IMAGE", "REEL": "VIDEO", "ALBUM": "CAROUSEL"}.get(name, name)
    try:
        return MediaType(name)
    except ValueError:
        raise FieldNormalizationError("INVALID_MEDIA_TYPE", "Unsupported media type") from None


def normalize_integer(value: str | None) -> int | None:
    value = (value or "").strip()
    if not value or value.lower() == "null":
        return None
    if not re.fullmatch(r"[0-9]+", value):
        raise FieldNormalizationError("INVALID_INTEGER", "Metric must be a non-negative integer or NULL")
    # Avoid Python's enormous-integer conversion limit and PostgreSQL overflow.
    digits = value.lstrip("0") or "0"
    if len(digits) > 19 or int(digits) > MAX_BIGINT:
        raise FieldNormalizationError("INTEGER_OUT_OF_RANGE", "Metric exceeds PostgreSQL BIGINT range")
    return int(digits)


def normalize_datetime(value: str | None) -> datetime:
    value = (value or "").strip()
    # Explicit calendar date/time with offset. Do not infer timezone or accept date-only values.
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})", value):
        raise FieldNormalizationError("INVALID_DATETIME", "Expected ISO 8601 datetime with timezone")
    offset = re.search(r"[+-](\d{2}):(\d{2})$", value)
    if offset and (int(offset[1]) > 23 or int(offset[2]) > 59):
        raise FieldNormalizationError("INVALID_DATETIME", "Invalid timezone offset")
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        raise FieldNormalizationError("INVALID_DATETIME", "Invalid calendar datetime") from None
    return result


def normalize_date(value: str | None) -> date:
    value = (value or "").strip()
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise FieldNormalizationError("INVALID_DATE", "Expected YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise FieldNormalizationError("INVALID_DATE", "Invalid calendar date") from None


def normalize_hashtags(value: str | None) -> list[str]:
    result = []
    for token in (value or "").split(";"):
        token = token.strip()
        if not token:
            continue
        token = token if token.startswith("#") else "#" + token
        if token == "#" or any(c.isspace() for c in token) or "," in token or "#" in token[1:]:
            raise FieldNormalizationError("INVALID_HASHTAGS", "Separate non-empty hashtags with semicolons")
        if token not in result:
            result.append(token)
    return result


def normalize_keywords(value: str | None) -> list[str]:
    keyword = optional_text(value)
    return [keyword] if keyword is not None else []


def is_sensitive_field(name: str) -> bool:
    name = re.sub(r"[^a-z0-9]", "", name.lower())
    return any(marker in name for marker in ("password", "secret", "token", "apikey", "authorization", "credential", "privatekey"))


def safe_raw(data: Mapping[str, str]) -> dict[str, str]:
    # API adapters must omit credentials; reject known credential fields defensively.
    if any(is_sensitive_field(name) for name in data):
        raise FieldNormalizationError("SENSITIVE_FIELD", "Credential fields cannot be retained as raw data")
    return dict(data)


T = TypeVar("T")


class _Fields:
    def __init__(self, data: Mapping[str, str], row_number: int | None):
        self.data, self.row_number = data, row_number
        self.errors: list[ValidationError] = []

    def parse(self, name: str, parser: Callable[[str | None], T]) -> T | None:
        try:
            return parser(self.data.get(name))
        except FieldNormalizationError as error:
            self.errors.append(ValidationError(self.row_number, name, error.code, error.message))
            return None

    def finish(self) -> None:
        if self.errors:
            raise RowValidationError(self.errors)


class Normalizer:
    """Adapters supply canonical field names and string values; no CSV/DB dependency."""

    def normalize_post(self, data: Mapping[str, str], source_type: SourceType,
                       row_number: int | None = None, raw_data: Mapping[str, str] | None = None,
                       *, include_followers: bool = False) -> NormalizedPost | NormalizedCompetitorData:
        source_type = SourceType(source_type)
        raw = safe_raw(data if raw_data is None else raw_data)
        fields = _Fields(data, row_number)
        platform = fields.parse("platform", normalize_platform)
        post_id = fields.parse("platform_post_id", lambda v: required_text(v, 255))
        account = fields.parse("account_name", lambda v: required_text(v, 100)) if source_type != SourceType.MARKET else optional_text(data.get("account_name"))
        posted_at = fields.parse("posted_at", normalize_datetime)
        media = fields.parse("media_type", normalize_media_type)
        metrics = {name: fields.parse(name, normalize_integer) for name in POST_METRICS}
        hashtags = fields.parse("hashtags", normalize_hashtags)
        followers = fields.parse("followers", normalize_integer) if include_followers else None
        fields.finish()
        post = NormalizedPost(source_type=source_type, platform=platform, platform_post_id=post_id,
                              account_name=account, posted_at=posted_at, media_type=media,
                              text=optional_text(data.get("text")), permalink=optional_text(data.get("permalink")),
                              hashtags=hashtags, keywords=normalize_keywords(data.get("keyword")),
                              raw_data=raw, row_number=row_number, **metrics)
        return NormalizedCompetitorData(post, followers) if include_followers else post

    def normalize_account_metric(self, data: Mapping[str, str], row_number: int | None = None,
                                 raw_data: Mapping[str, str] | None = None) -> NormalizedAccountMetric:
        raw = safe_raw(data if raw_data is None else raw_data)
        fields = _Fields(data, row_number)
        platform = fields.parse("platform", normalize_platform)
        account = fields.parse("account_name", lambda v: required_text(v, 100))
        recorded_date = fields.parse("recorded_date", normalize_date)
        metrics = {name: fields.parse(name, normalize_integer) for name in ACCOUNT_METRICS}
        fields.finish()
        return NormalizedAccountMetric(platform, account, recorded_date, raw_metrics=raw, row_number=row_number, **metrics)

    def normalize_trend(self, data: Mapping[str, str], row_number: int | None = None,
                        raw_data: Mapping[str, str] | None = None) -> NormalizedTrendData:
        return NormalizedTrendData(self.normalize_post(data, SourceType.MARKET, row_number, raw_data))
