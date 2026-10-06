from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.dto.normalized import MediaType, Platform


class AnalysisPlatform(StrEnum):
    ALL = "ALL"
    X = "X"
    INSTAGRAM = "INSTAGRAM"


class SortField(StrEnum):
    posted_at = "posted_at"
    reach = "reach"
    likes = "likes"
    comments = "comments"
    shares = "shares"
    saves = "saves"
    engagement = "engagement"
    engagement_rate = "engagement_rate"


class SortOrder(StrEnum):
    asc = "asc"
    desc = "desc"


class Response(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RateGroup(Response):
    platform: Platform
    denominator_type: str
    post_count: int
    avg_engagement_rate: float | None


class Aggregate(Response):
    post_count: int
    engagement_total: int | None
    avg_engagement: float | None
    avg_engagement_rate: float | None
    rate_groups: list[RateGroup]


class FollowerValue(Response):
    platform: Platform
    account_id: UUID
    account_name: str
    recorded_date: date | None
    followers: int | None


class KPI(Response):
    posts: int
    reach: int | None
    impressions: int | None
    engagement: int | None
    engagement_rate: float | None
    followers: int | None
    followers_by_account: list[FollowerValue]
    avg_engagement: float | None
    rate_groups: list[RateGroup]


class DailyAggregate(Aggregate):
    date: date


class MediaAggregate(Aggregate):
    media_type: MediaType | None
    posts: int


class Analytics(Response):
    kpis: KPI
    engagement_trend: list[DailyAggregate]
    media_type_performance: list[MediaAggregate]
    timezone: str = "UTC"


class Post(Response):
    post_id: UUID
    account_id: UUID | None
    account_name: str | None
    author_name: str | None
    platform: Platform
    posted_at: datetime
    text: str | None
    media_type: MediaType | None
    permalink: str | None
    hashtags: list[str]


class Metrics(Response):
    recorded_at: datetime | None
    impressions: int | None
    reach: int | None
    views: int | None
    likes: int | None
    comments: int | None
    shares: int | None
    saves: int | None
    engagement: int | None
    engagement_rate: float | None
    denominator_type: str | None
    denominator_value: int | None


class PostItem(Post, Metrics):
    pass


class PostPage(Response):
    items: list[PostItem]
    total: int
    page: int
    page_size: int


class Comparison(Response):
    vs_average_rate: float | None
    rank: int | None
    total_posts: int
    comparable_posts: int
    basis: str = "Same platform and denominator within the selected filters; ER descending"


class TopicLink(Response):
    topic_id: UUID
    topic_name: str
    is_active: bool
    match_type: str


class PostDetail(Response):
    post: Post
    metrics: Metrics
    comparison: Comparison
    topics: list[TopicLink]
