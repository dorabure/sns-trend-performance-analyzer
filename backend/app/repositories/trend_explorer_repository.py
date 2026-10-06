"""Read-only Term snapshots and matched MARKET posts; never rebuild trends."""
from datetime import datetime, time, timezone

from sqlalchemy import and_, func, select

from app.db.models import PostMetric, PostTerm, PostTopic, SNSAccount, SNSPost, TrendDaily, WatchTerm, WatchTopic
from app.repositories.my_account_repository import METRICS, MyAccountRepository


TREND_FIELDS = ("post_count", "engagement_count", "avg_engagement", "post_growth_rate",
    "engagement_growth_rate", "acceleration_rate", "post_growth_score", "engagement_growth_score",
    "engagement_level_score", "acceleration_score", "trend_score")


class TrendExplorerRepository(MyAccountRepository):
    @staticmethod
    def topic(session, project_id, topic_id):
        return session.scalar(select(WatchTopic).where(WatchTopic.project_id == project_id,
                                                     WatchTopic.topic_id == topic_id))

    @staticmethod
    def terms(session, project_id, topic_id=None, term_ids=None):
        query = select(WatchTerm.term_id, WatchTerm.term, WatchTerm.term_type, WatchTopic.topic_id,
                       WatchTopic.topic_name).join(WatchTopic, WatchTopic.topic_id == WatchTerm.topic_id).where(
            WatchTopic.project_id == project_id, WatchTopic.is_active.is_(True), WatchTerm.is_active.is_(True))
        if topic_id is not None:
            query = query.where(WatchTerm.topic_id == topic_id)
        if term_ids is not None:
            query = query.where(WatchTerm.term_id.in_(term_ids))
        return session.execute(query.order_by(WatchTerm.term, WatchTerm.term_id)).mappings().all()

    @staticmethod
    def snapshots(session, project_id, terms, platforms, filters, latest=False):
        # Join both IDs: corrupted cross-topic trend rows cannot inherit another term's project.
        query = select(TrendDaily.term_id, TrendDaily.platform, TrendDaily.trend_date,
            *(getattr(TrendDaily, name) for name in TREND_FIELDS),
            func.row_number().over(partition_by=(TrendDaily.term_id, TrendDaily.platform),
                order_by=TrendDaily.trend_date.desc()).label("position"))\
            .join(WatchTerm, and_(WatchTerm.term_id == TrendDaily.term_id, WatchTerm.topic_id == TrendDaily.topic_id))\
            .join(WatchTopic, WatchTopic.topic_id == WatchTerm.topic_id).where(
                WatchTopic.project_id == project_id, WatchTopic.is_active.is_(True), WatchTerm.is_active.is_(True),
                TrendDaily.term_id.in_([t["term_id"] for t in terms]), TrendDaily.platform.in_(platforms),
                TrendDaily.window_days == 7, TrendDaily.trend_date >= filters.start, TrendDaily.trend_date <= filters.end)
        if latest:
            rows = query.subquery()
            query = select(rows).where(rows.c.position == 1)
        return session.execute(query).mappings().all()

    @staticmethod
    def popular(session, project_id, topic_id, platforms, filters, term_ids=None):
        conditions = [SNSPost.project_id == project_id, SNSPost.source_type == "MARKET",
            SNSPost.platform.in_(platforms),
            SNSPost.posted_at >= datetime.combine(filters.start, time.min, timezone.utc),
            SNSPost.posted_at <= datetime.combine(filters.end, time.max, timezone.utc),
            select(PostTopic.post_id).where(PostTopic.post_id == SNSPost.post_id,
                                           PostTopic.topic_id == topic_id).exists()]
        if term_ids is not None:
            conditions.append(select(PostTerm.post_id).where(PostTerm.post_id == SNSPost.post_id,
                                                           PostTerm.term_id.in_(term_ids)).exists())
        # Materialize once: avoid repeated match predicates/window evaluation when
        # PostgreSQL chooses a nested-loop plan after many import/delete operations.
        scoped = select(SNSPost.post_id).where(*conditions).cte("scoped_market_posts").prefix_with("MATERIALIZED")
        latest = select(PostMetric.post_id, PostMetric.recorded_at, *(getattr(PostMetric, n) for n in METRICS),
            func.row_number().over(partition_by=PostMetric.post_id,
                order_by=PostMetric.recorded_at.desc()).label("position"))\
            .join(scoped, scoped.c.post_id == PostMetric.post_id).cte("market_metric_snapshots").prefix_with("MATERIALIZED")
        return session.execute(select(SNSPost.post_id, SNSPost.account_id, SNSPost.author_name,
            SNSPost.platform, SNSPost.posted_at, SNSPost.text, SNSPost.media_type, SNSPost.permalink,
            SNSPost.hashtags, SNSAccount.account_name, latest.c.recorded_at, *(latest.c[n] for n in METRICS))
            .join(scoped, scoped.c.post_id == SNSPost.post_id)
            .outerjoin(SNSAccount, and_(SNSAccount.account_id == SNSPost.account_id, SNSAccount.project_id == project_id))
            .outerjoin(latest, and_(latest.c.post_id == SNSPost.post_id, latest.c.position == 1))
            ).mappings().all()
