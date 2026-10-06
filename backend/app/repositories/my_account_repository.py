"""Bulk read queries. Unicode filtering is applied without rewriting DB text."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

from sqlalchemy import and_, func, select, true

from app.db.models import AccountMetric, PostMetric, PostTopic, Project, ProjectPlatform, SNSAccount, SNSPost, WatchTopic
from app.services.matching_service import normalize_term

METRICS = ("impressions", "reach", "views", "likes", "comments", "shares", "saves")


@dataclass(frozen=True)
class Filters:
    start: date
    end: date
    platform: str | None = None
    media_type: str | None = None
    keyword: str | None = None
    hashtag: str | None = None


class MyAccountRepository:
    @staticmethod
    def latest_metric(post_id):
        # Unique(post_id, recorded_at) and the existing descending index give
        # one latest row, including NULL metrics, without rescanning a window
        # result for each post when cardinality estimates are inaccurate.
        return select(PostMetric.recorded_at, *(getattr(PostMetric, n) for n in METRICS)).where(
            PostMetric.post_id == post_id).order_by(PostMetric.recorded_at.desc()).limit(1).lateral('latest_post_metric')

    @staticmethod
    def project(session, project_id):
        return session.get(Project, project_id)

    @staticmethod
    def platforms(session, project_id):
        return list(session.scalars(select(ProjectPlatform.platform).where(ProjectPlatform.project_id == project_id)))

    @staticmethod
    def conditions(project_id, platforms, filters=None, post_id=None):
        conditions = [SNSPost.project_id == project_id, SNSPost.source_type == "OWN"]
        if post_id is None:
            conditions.append(SNSPost.platform.in_(platforms))
        else:
            conditions.append(SNSPost.post_id == post_id)
        if filters:
            beginning = datetime.combine(filters.start, time.min, timezone.utc)
            # Use next-day exclusive boundary, without overflowing date.max.
            ending = datetime.combine(filters.end, time.max, timezone.utc)
            conditions.extend([SNSPost.posted_at >= beginning, SNSPost.posted_at <= ending])
            if filters.media_type:
                conditions.append(SNSPost.media_type == filters.media_type)
        return conditions

    @staticmethod
    def query(project_id, platforms, filters=None, post_id=None, lean=False, page_ids=None):
        conditions = MyAccountRepository.conditions(project_id, platforms, filters, post_id)
        if page_ids is not None:
            conditions.append(SNSPost.post_id.in_(select(page_ids.c.post_id)))
        latest = MyAccountRepository.latest_metric(SNSPost.post_id)
        if lean:
            return select(SNSPost.account_id, SNSPost.platform, SNSPost.posted_at, SNSPost.media_type,
                *(latest.c[n] for n in METRICS)).select_from(SNSPost).outerjoin(latest, true()).where(*conditions)
        # Defensive project join on account; posts from inactive OWN accounts remain included.
        return select(SNSPost.post_id, SNSPost.account_id, SNSPost.author_name, SNSPost.platform,
            SNSPost.posted_at, SNSPost.text, SNSPost.media_type, SNSPost.permalink, SNSPost.hashtags,
            SNSAccount.account_name, latest.c.recorded_at, *(latest.c[n] for n in METRICS))\
            .outerjoin(SNSAccount, and_(SNSAccount.account_id == SNSPost.account_id, SNSAccount.project_id == project_id))\
            .outerjoin(latest, true()).where(*conditions)

    def posts(self, session, project_id, platforms, filters=None, post_id=None, lean=False):
        # Unicode matching still uses the original full text/hashtags in Python.
        filtered = filters and (filters.keyword or filters.hashtag)
        rows = session.execute(self.query(project_id, platforms, filters, post_id, lean=lean and not filtered)).mappings().all()
        if filters:
            if filters.keyword:
                key = normalize_term(filters.keyword)
                rows = [r for r in rows if key in normalize_term(r["text"] or "")]
            if filters.hashtag:
                key = normalize_term(filters.hashtag)
                rows = [r for r in rows if any(normalize_term(tag) == key for tag in r["hashtags"])]
        return rows

    def page_posts(self, session, project_id, platforms, filters, page, page_size, order):
        conditions = self.conditions(project_id, platforms, filters)
        timestamp = SNSPost.posted_at.desc() if order == 'desc' else SNSPost.posted_at.asc()
        # UUID tie order is descending for BOTH timestamp directions, as before.
        page_ids = select(SNSPost.post_id).where(*conditions).order_by(timestamp.nulls_last(), SNSPost.post_id.desc())\
            .offset((page - 1) * page_size).limit(page_size).cte('own_page_posts').prefix_with('MATERIALIZED')
        total = select(func.count().label('total')).select_from(SNSPost).where(*conditions).cte('own_page_total')
        posts = self.query(project_id, platforms, filters, page_ids=page_ids).order_by(
            timestamp.nulls_last(), SNSPost.post_id.desc()).lateral('own_page_details')
        # One SQL statement including total, even for an empty/out-of-range page.
        page_order = posts.c.posted_at.desc() if order == 'desc' else posts.c.posted_at.asc()
        rows = session.execute(select(total.c.total, posts).select_from(total.outerjoin(posts, true())).order_by(
            page_order.nulls_last(), posts.c.post_id.desc())).mappings().all()
        return [r for r in rows if r['post_id'] is not None], rows[0]['total']

    @staticmethod
    def followers(session, project_id, platforms, end):
        latest = select(AccountMetric.account_id, AccountMetric.recorded_date, AccountMetric.followers,
            func.row_number().over(partition_by=AccountMetric.account_id, order_by=AccountMetric.recorded_date.desc()).label("position"))\
            .join(SNSAccount, SNSAccount.account_id == AccountMetric.account_id).where(
                SNSAccount.project_id == project_id, SNSAccount.account_role == "OWN",
                SNSAccount.platform.in_(platforms), SNSAccount.is_active.is_(True), AccountMetric.recorded_date <= end).subquery()
        return session.execute(select(SNSAccount.platform, SNSAccount.account_id, SNSAccount.account_name,
            latest.c.recorded_date, latest.c.followers).outerjoin(latest, and_(
                latest.c.account_id == SNSAccount.account_id, latest.c.position == 1)).where(
                SNSAccount.project_id == project_id, SNSAccount.platform.in_(platforms),
                SNSAccount.account_role == "OWN", SNSAccount.is_active.is_(True))
            .order_by(SNSAccount.platform, SNSAccount.account_id)).mappings().all()

    @staticmethod
    def topics(session, project_id, post_id):
        return session.execute(select(WatchTopic.topic_id, WatchTopic.topic_name, WatchTopic.is_active, PostTopic.match_type)
            .join(PostTopic, PostTopic.topic_id == WatchTopic.topic_id).where(
                WatchTopic.project_id == project_id, PostTopic.post_id == post_id)
            .order_by(WatchTopic.topic_name, WatchTopic.topic_id)).mappings().all()

    @staticmethod
    def paginate(items, page, page_size, sort, order):
        # Explicit whitelist supplied by typed API. NULLs always last, stable UUID tie breaker.
        ordered = sorted(items, key=lambda p: str(p.post_id), reverse=True)
        known = [p for p in ordered if getattr(p, sort) is not None]
        unknown = [p for p in ordered if getattr(p, sort) is None]
        known.sort(key=lambda p: getattr(p, sort), reverse=order == "desc")
        return (known + unknown)[(page - 1) * page_size:page * page_size]
