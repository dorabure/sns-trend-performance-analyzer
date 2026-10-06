"""Topic snapshots and SQL coverage aggregation; no writes or rematching."""
from datetime import datetime, time, timezone

from sqlalchemy import and_, func, or_, select

from app.db.models import PostTopic, SNSAccount, SNSPost, TrendDaily, WatchTopic
from app.repositories.my_account_repository import MyAccountRepository


class GapAnalysisRepository(MyAccountRepository):
    @staticmethod
    def topics(session, project_id):
        return session.execute(select(WatchTopic.topic_id, WatchTopic.topic_name).where(
            WatchTopic.project_id == project_id, WatchTopic.is_active.is_(True))).mappings().all()

    @staticmethod
    def snapshots(session, project_id, platforms, filters):
        ranked = select(TrendDaily.topic_id, TrendDaily.platform, TrendDaily.trend_date, TrendDaily.trend_score,
            func.row_number().over(partition_by=(TrendDaily.topic_id, TrendDaily.platform),
                order_by=TrendDaily.trend_date.desc()).label('position')).join(
                    WatchTopic, WatchTopic.topic_id == TrendDaily.topic_id).where(
                WatchTopic.project_id == project_id, WatchTopic.is_active.is_(True),
                TrendDaily.term_id.is_(None), TrendDaily.window_days == 7,
                TrendDaily.platform.in_(platforms), TrendDaily.trend_date >= filters.start,
                TrendDaily.trend_date <= filters.end).subquery()
        return session.execute(select(ranked).where(ranked.c.position == 1)).mappings().all()

    @staticmethod
    def coverage(session, project_id, platforms, filters):
        # OWN retains historical inactive-account posts, as in Phase7. Competitors must be active.
        scoped = select(SNSPost.post_id, SNSPost.platform, SNSPost.source_type).join(SNSAccount, and_(
            SNSAccount.account_id == SNSPost.account_id, SNSAccount.project_id == SNSPost.project_id,
            SNSAccount.platform == SNSPost.platform, SNSAccount.account_role == SNSPost.source_type)).where(
                SNSPost.project_id == project_id, SNSPost.platform.in_(platforms),
                SNSPost.source_type.in_(['OWN', 'COMPETITOR']),
                or_(SNSPost.source_type == 'OWN', SNSAccount.is_active.is_(True)),
                SNSPost.posted_at >= datetime.combine(filters.start, time.min, timezone.utc),
                SNSPost.posted_at <= datetime.combine(filters.end, time.max, timezone.utc))\
            .cte('gap_period_posts').prefix_with('MATERIALIZED')
        totals = session.execute(select(scoped.c.platform, scoped.c.source_type,
            func.count(func.distinct(scoped.c.post_id)).label('total_posts')).group_by(
                scoped.c.platform, scoped.c.source_type)).mappings().all()
        matched = session.execute(select(PostTopic.topic_id, scoped.c.platform, scoped.c.source_type,
            func.count(func.distinct(scoped.c.post_id)).label('matched_posts')).join(
                scoped, scoped.c.post_id == PostTopic.post_id).join(WatchTopic, WatchTopic.topic_id == PostTopic.topic_id)
            .where(WatchTopic.project_id == project_id, WatchTopic.is_active.is_(True))
            .group_by(PostTopic.topic_id, scoped.c.platform, scoped.c.source_type)).mappings().all()
        return totals, matched
