from datetime import date
from enum import StrEnum
from uuid import UUID

from app.schemas.my_account import PostItem, Response


class TrendMetric(StrEnum):
    post_count = "post_count"
    engagement = "engagement"
    trend_score = "trend_score"


class Direction(StrEnum):
    UP = "UP"
    FLAT = "FLAT"
    DOWN = "DOWN"
    UNKNOWN = "UNKNOWN"


class RankingItem(Response):
    topic_id: UUID
    topic_name: str
    term_id: UUID
    keyword: str
    term_type: str
    platform: str
    trend_date: date
    post_count: int
    engagement_count: int
    avg_engagement: float | None
    post_growth_rate: float | None
    engagement_growth_rate: float | None
    acceleration_rate: float | None
    post_growth_score: float | None
    engagement_growth_score: float | None
    engagement_level_score: float | None
    acceleration_score: float | None
    trend_score: float | None
    trend_direction: Direction


class Ranking(Response):
    score_window_days: int = 7
    score_as_of: date | None
    items: list[RankingItem]


class Point(Response):
    date: date
    value: float | int | None
    row_present: bool


class Series(Response):
    topic_id: UUID
    topic_name: str
    term_id: UUID
    term_name: str
    term: str
    term_type: str
    platform: str
    values: list[Point]


class Timeseries(Response):
    metric: TrendMetric
    timezone: str = "UTC"
    series: list[Series]


class TopPosts(Response):
    items: list[PostItem]
