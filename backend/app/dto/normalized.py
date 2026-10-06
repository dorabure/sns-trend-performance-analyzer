from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Generic, TypeVar


class Platform(StrEnum):
    X = "X"
    INSTAGRAM = "INSTAGRAM"


class SourceType(StrEnum):
    OWN = "OWN"
    COMPETITOR = "COMPETITOR"
    MARKET = "MARKET"


class MediaType(StrEnum):
    TEXT = "TEXT"
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    CAROUSEL = "CAROUSEL"
    OTHER = "OTHER"


@dataclass(frozen=True)
class NormalizedPost:
    source_type: SourceType
    platform: Platform
    platform_post_id: str
    posted_at: datetime
    account_name: str | None = None
    text: str | None = None
    media_type: MediaType | None = None
    permalink: str | None = None
    impressions: int | None = None
    reach: int | None = None
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    hashtags: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    raw_data: dict[str, Any] = field(default_factory=dict)
    row_number: int | None = None


@dataclass(frozen=True)
class NormalizedAccountMetric:
    platform: Platform
    account_name: str
    recorded_date: date
    followers: int | None = None
    following: int | None = None
    post_count: int | None = None
    raw_metrics: dict[str, Any] = field(default_factory=dict)
    row_number: int | None = None


@dataclass(frozen=True)
class NormalizedTrendData:
    post: NormalizedPost

    @property
    def keywords(self) -> list[str]:
        return self.post.keywords


@dataclass(frozen=True)
class NormalizedCompetitorData:
    post: NormalizedPost
    followers: int | None


@dataclass(frozen=True)
class ValidationError:
    row_number: int | None
    field: str
    code: str
    message: str


T = TypeVar("T")


@dataclass(frozen=True)
class ProviderResult(Generic[T]):
    records: list[T]
    errors: list[ValidationError]
    total_rows: int

    @property
    def valid_rows(self) -> int:
        return len(self.records)

    @property
    def invalid_rows(self) -> int:
        return self.total_rows - self.valid_rows


NormalizedRecord = NormalizedPost | NormalizedAccountMetric | NormalizedTrendData | NormalizedCompetitorData
