from datetime import date
from uuid import UUID

from app.dto.normalized import Platform
from app.schemas.my_account import PostItem, RateGroup, Response


class AccountIdentity(Response):
    account_id: UUID
    account_name: str
    display_name: str | None
    platform: Platform
    role: str


class AccountAnalytics(AccountIdentity):
    followers: int | None
    followers_as_of: date | None
    posts: int
    posting_frequency: float
    avg_views: float | None
    avg_likes: float | None
    avg_comments: float | None
    avg_shares: float | None
    avg_engagement: float | None
    avg_engagement_rate: float | None
    engagement_rate_groups: list[RateGroup]


class Analytics(Response):
    accounts: list[AccountAnalytics]
    timezone: str = "UTC"
    posting_frequency_unit: str = "posts/day"


class TopicAccount(AccountIdentity):
    matched_posts: int
    total_posts: int
    ratio: float | None


class TopicDistribution(Response):
    topic_id: UUID
    topic_name: str
    accounts: list[TopicAccount]


class Distribution(Response):
    topics: list[TopicDistribution]
    timezone: str = "UTC"
    overlapping_topics: bool = True


class CompetitorPost(PostItem):
    display_name: str | None


class TopPosts(Response):
    items: list[CompetitorPost]
