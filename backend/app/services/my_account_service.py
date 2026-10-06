from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from uuid import UUID

from app.normalizers.common import FieldNormalizationError, normalize_hashtags
from app.repositories.my_account_repository import Filters, METRICS, MyAccountRepository
from app.schemas.my_account import (Aggregate, Analytics, Comparison, DailyAggregate, FollowerValue, KPI,
    MediaAggregate, Metrics, Post, PostDetail, PostItem, PostPage, RateGroup, TopicLink)
from app.services.settings_service import SettingsFailure
from app.services.trend_calculation import RAW_QUANTUM, calculate_engagement, rounded


def engagement_rate(engagement, reach, impressions, views):
    for name, denominator in [("reach", reach), ("impressions", impressions), ("views", views)]:
        if denominator is not None:
            if denominator == 0 or engagement is None:
                return None, name, denominator
            with localcontext() as ctx:
                ctx.prec = 50
                return Decimal(engagement) / Decimal(denominator) * 100, name, denominator
    return None, None, None


def number(value):
    return float(rounded(value, RAW_QUANTUM)) if value is not None else None


def known_sum(values):
    known = [v for v in values if v is not None]
    return sum(known) if known else None


def average(values):
    known = [v for v in values if v is not None]
    if not known:
        return None
    with localcontext() as ctx:
        ctx.prec = 50
        return sum((Decimal(v) for v in known), Decimal(0)) / len(known)


@dataclass(frozen=True, slots=True)
class AnalyticsItem:
    """Internal aggregate facts: no post text, links or public response changes."""
    account_id: UUID | None
    platform: str
    posted_at: datetime
    media_type: str | None
    impressions: int | None
    reach: int | None
    views: int | None
    likes: int | None
    comments: int | None
    shares: int | None
    saves: int | None
    engagement: int | None
    denominator_type: str | None
    rate: Decimal | None


class MyAccountService:
    def __init__(self, session_factory, repository=None):
        self.session_factory = session_factory
        self.repository = repository or MyAccountRepository()

    @contextmanager
    def read(self, project_id):
        try:
            with self.session_factory() as s:
                # A consistent, read-only snapshot across posts, metrics, followers and topics.
                s.connection(execution_options={"isolation_level": "REPEATABLE READ", "postgresql_readonly": True})
                if self.repository.project(s, project_id) is None:
                    raise SettingsFailure(404, "NOT_FOUND", "Project was not found")
                yield s
        except SettingsFailure:
            raise
        except Exception:
            raise SettingsFailure(500, "ANALYTICS_ERROR", "Analysis could not be retrieved") from None

    @staticmethod
    def filters(start, end, platform=None, media_type=None, keyword=None, hashtag=None):
        if start > end:
            raise SettingsFailure(400, "INVALID_PERIOD", "Start date must not be after end date")
        if (end - start).days >= 3660:
            raise SettingsFailure(400, "INVALID_PERIOD", "Select a period of at most 3660 days")
        tag = None
        if hashtag and hashtag.strip():
            try:
                tags = normalize_hashtags(hashtag)
                if len(tags) != 1 or ";" in hashtag:
                    raise ValueError()
                tag = tags[0]
            except (FieldNormalizationError, ValueError):
                raise SettingsFailure(400, "INVALID_HASHTAG", "Enter one non-empty hashtag without spaces") from None
        return Filters(start, end, None if platform in (None, "ALL") else platform,
                       media_type, keyword.strip() if keyword else None, tag)

    def load(self, s, project_id, filters, analytics=False):
        enabled = self.repository.platforms(s, project_id)
        platforms = [filters.platform] if filters.platform in enabled else [] if filters.platform else enabled
        rows = self.repository.posts(s, project_id, platforms, filters, lean=True) if analytics else self.repository.posts(s, project_id, platforms, filters)
        converter = self.analytics_item if analytics else self.item
        return [converter(r) for r in rows], platforms

    @staticmethod
    def analytics_item(row):
        engagement = calculate_engagement(*(row[n] for n in ('likes', 'comments', 'shares', 'saves')))
        rate, kind, _ = engagement_rate(engagement, row['reach'], row['impressions'], row['views'])
        return AnalyticsItem(**{n: row[n] for n in ('account_id', 'platform', 'posted_at', 'media_type', *METRICS)},
            engagement=engagement, denominator_type=kind, rate=rate)

    @staticmethod
    def item(row):
        data = dict(row)
        engagement = calculate_engagement(*(data[n] for n in ("likes", "comments", "shares", "saves")))
        rate, kind, denominator = engagement_rate(engagement, data["reach"], data["impressions"], data["views"])
        return PostItem(**data, engagement=engagement, engagement_rate=number(rate),
                        denominator_type=kind, denominator_value=denominator)

    @staticmethod
    def raw_rate(item):
        if isinstance(item, AnalyticsItem):
            return item.rate
        return engagement_rate(item.engagement, item.reach, item.impressions, item.views)[0]

    def aggregate(self, items):
        cohorts = defaultdict(list)
        for p in items:
            if self.raw_rate(p) is not None:
                cohorts[(p.platform, p.denominator_type)].append(p)
        groups = [RateGroup(platform=platform, denominator_type=kind, post_count=len(posts),
                    avg_engagement_rate=number(average([self.raw_rate(p) for p in posts])))
                  for (platform, kind), posts in sorted(cohorts.items())]
        # Different measurement bases must not become a single unqualified average.
        avg_rate = groups[0].avg_engagement_rate if len(groups) == 1 else None
        return Aggregate(post_count=len(items), engagement_total=known_sum([p.engagement for p in items]),
                         avg_engagement=number(average([p.engagement for p in items])),
                         avg_engagement_rate=avg_rate, rate_groups=groups)

    def analytics(self, project_id, filters):
        with self.read(project_id) as s:
            return self.analytics_in_session(s, project_id, filters)

    def analytics_in_session(self, s, project_id, filters):
        """Caller owns the read-only transaction; also used by Overview."""
        items, platforms = self.load(s, project_id, filters, analytics=True)
        followers = [FollowerValue(**r) for r in self.repository.followers(s, project_id, platforms, filters.end)]
        kpis = self.kpis(items, followers)
        return self.analytics_from_items(items, kpis, filters)

    def kpis(self, items, followers):
        aggregate = self.aggregate(items)
        return KPI(posts=len(items), reach=known_sum([p.reach for p in items]),
                   impressions=known_sum([p.impressions for p in items]), engagement=aggregate.engagement_total,
                   engagement_rate=aggregate.avg_engagement_rate, avg_engagement=aggregate.avg_engagement,
                   rate_groups=aggregate.rate_groups, followers=followers[0].followers if len(followers) == 1 else None,
                   followers_by_account=followers)

    def analytics_from_items(self, items, kpis, filters):
        days, media = defaultdict(list), defaultdict(list)
        for p in items:
            days[p.posted_at.astimezone(timezone.utc).date()].append(p)
            media[p.media_type].append(p)
        trend = []
        day = filters.start
        for offset in range((filters.end - filters.start).days + 1):
            day = filters.start + timedelta(days=offset)
            trend.append(DailyAggregate(date=day, **self.aggregate(days[day]).model_dump()))
        performance = [MediaAggregate(media_type=kind, posts=len(posts), **self.aggregate(posts).model_dump())
                       for kind, posts in sorted(media.items(), key=lambda pair: (pair[0] is None, pair[0] or ""))]
        return Analytics(kpis=kpis, engagement_trend=trend, media_type_performance=performance)

    def posts(self, project_id, filters, page, page_size, sort, order):
        with self.read(project_id) as s:
            if sort == 'posted_at' and not filters.keyword and not filters.hashtag:
                enabled = self.repository.platforms(s, project_id)
                platforms = [filters.platform] if filters.platform in enabled else [] if filters.platform else enabled
                rows, total = self.repository.page_posts(s, project_id, platforms, filters, page, page_size, order)
                return PostPage(items=[self.item(r) for r in rows], total=total, page=page, page_size=page_size)
            items, _ = self.load(s, project_id, filters)
            return PostPage(items=self.repository.paginate(items, page, page_size, sort, order),
                            total=len(items), page=page, page_size=page_size)

    def detail(self, project_id, post_id, filters=None):
        with self.read(project_id) as s:
            rows = self.repository.posts(s, project_id, [], post_id=post_id)
            if not rows:
                raise SettingsFailure(404, "NOT_FOUND", "OWN post was not found")
            item = self.item(rows[0])
            if filters is None:
                # Without UI context compare the full enabled OWN history, no arbitrary period inference.
                platforms = self.repository.platforms(s, project_id)
                candidates = [self.item(r) for r in self.repository.posts(s, project_id, platforms)]
            else:
                candidates, _ = self.load(s, project_id, filters)
            comparable = [p for p in candidates if p.platform == item.platform and
                          p.denominator_type == item.denominator_type and self.raw_rate(p) is not None]
            rate = self.raw_rate(item)
            avg = average([self.raw_rate(p) for p in comparable])
            in_scope = any(p.post_id == item.post_id for p in comparable)
            rank = 1 + sum(self.raw_rate(p) > rate for p in comparable) if rate is not None and in_scope else None
            with localcontext() as ctx:
                ctx.prec = 50
                difference = (rate - avg) / avg * 100 if rate is not None and avg and in_scope else None
            comparison = Comparison(vs_average_rate=number(difference), rank=rank,
                                    total_posts=len(candidates), comparable_posts=len(comparable))
            fields = item.model_dump()
            return PostDetail(post=Post.model_validate(fields), metrics=Metrics.model_validate(fields), comparison=comparison,
                topics=[TopicLink(**r) for r in self.repository.topics(s, project_id, post_id)])
