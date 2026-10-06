"""Overview uses the Ver1.1 API names and typed additions for missing details."""
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field, JsonValue

from app.dto.normalized import Platform
from app.schemas.competitors import AccountAnalytics
from app.schemas.gap_analysis import GapItem
from app.schemas.my_account import FollowerValue, RateGroup, Response


class Period(Response):
    start: date = Field(serialization_alias='from')
    end: date = Field(serialization_alias='to')


class CountKPI(Response):
    value: int | None
    previous_value: int | None
    change: int | None
    change_rate: float | None


class RateKPI(Response):
    value: float | None
    previous_value: float | None
    change_point: float | None
    rate_groups: list[RateGroup]
    previous_rate_groups: list[RateGroup]


class OverviewKPIs(Response):
    reach: CountKPI
    engagement_rate: RateKPI
    followers: CountKPI
    posts: CountKPI
    impressions: CountKPI
    engagement: CountKPI
    followers_by_account: list[FollowerValue]


class Daily(Response):
    date: date
    posts: int
    reach: int | None
    engagement: int | None


class FollowerPoint(Response):
    date: date
    followers: int | None
    row_present: bool


class FollowerSeries(Response):
    account_id: UUID
    account_name: str
    platform: Platform
    values: list[FollowerPoint]


class PerformanceTrend(Response):
    daily: list[Daily]
    follower_series: list[FollowerSeries]


class TrendingTopic(Response):
    topic_id: UUID
    topic_name: str
    platform: Platform
    trend_date: date
    trend_score: float
    post_growth_rate: float | None
    engagement_growth_rate: float | None
    avg_engagement: float | None
    trend_direction: str


class Summary(Response):
    posts: int
    avg_engagement: float | None
    avg_engagement_rate: float | None
    rate_groups: list[RateGroup]
    followers_by_account: list[FollowerValue]
    account_count: int


class AISummary(Response):
    insight_id: UUID
    platform: Platform | None
    analysis_from: date
    analysis_to: date
    created_at: datetime
    content: JsonValue
    model_name: str | None
    prompt_version: str | None


class Overview(Response):
    timezone: str = 'UTC'
    period: Period
    previous_period: Period | None
    kpis: OverviewKPIs
    performance_trend: PerformanceTrend
    top_trends: list[TrendingTopic]
    competitor_summary: list[AccountAnalytics]
    own_summary: Summary
    competitor_aggregate: Summary
    top_opportunity: GapItem | None
    ai_summary: AISummary | None


class TrendMetric(StrEnum):
    reach = 'reach'
    engagement = 'engagement'
    followers = 'followers'
    posts = 'posts'


class ValuePoint(Response):
    date: date
    value: int | None


class MetricTrend(Response):
    timezone: str = 'UTC'
    metric: TrendMetric
    series: list[ValuePoint]
    follower_series: list[FollowerSeries]
