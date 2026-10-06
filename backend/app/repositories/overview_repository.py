"""Fixed bulk reads; no per-post, per-topic or per-account SELECT loops."""
from sqlalchemy import case, func, or_, select

from app.db.models import AIInsight, AccountMetric, SNSAccount, TrendDaily, WatchTopic
from app.repositories.my_account_repository import MyAccountRepository


class OverviewRepository(MyAccountRepository):
    @staticmethod
    def accounts(session, project_id, platforms):
        return session.execute(select(SNSAccount.account_id, SNSAccount.account_name,
            SNSAccount.display_name, SNSAccount.platform, SNSAccount.account_role.label('role')).where(
                SNSAccount.project_id == project_id, SNSAccount.platform.in_(platforms),
                SNSAccount.is_active.is_(True)).order_by(
                    SNSAccount.account_name, SNSAccount.platform, SNSAccount.account_id)).mappings().all()

    @staticmethod
    def follower_history(session, project_id, platforms, filters):
        return session.execute(select(AccountMetric.account_id, AccountMetric.recorded_date,
            AccountMetric.followers).join(SNSAccount, SNSAccount.account_id == AccountMetric.account_id).where(
                SNSAccount.project_id == project_id, SNSAccount.is_active.is_(True),
                SNSAccount.account_role == 'OWN', SNSAccount.platform.in_(platforms),
                AccountMetric.recorded_date >= filters.start,
                AccountMetric.recorded_date <= filters.end)).mappings().all()

    @staticmethod
    def top_trends(session, project_id, platforms, filters):
        ranked = select(WatchTopic.topic_name, TrendDaily.topic_id, TrendDaily.platform,
            TrendDaily.trend_date, TrendDaily.trend_score, TrendDaily.post_growth_rate,
            TrendDaily.engagement_growth_rate, TrendDaily.avg_engagement,
            func.row_number().over(partition_by=(TrendDaily.topic_id, TrendDaily.platform),
                order_by=TrendDaily.trend_date.desc()).label('position')).join(
                    WatchTopic, WatchTopic.topic_id == TrendDaily.topic_id).where(
                WatchTopic.project_id == project_id, WatchTopic.is_active.is_(True),
                TrendDaily.term_id.is_(None), TrendDaily.window_days == 7,
                TrendDaily.platform.in_(platforms), TrendDaily.trend_date >= filters.start,
                TrendDaily.trend_date <= filters.end).subquery()
        # Filter NULL only AFTER selecting latest; do not backfill an older score.
        return session.execute(select(ranked).where(ranked.c.position == 1,
            ranked.c.trend_score.is_not(None)).order_by(ranked.c.trend_score.desc(),
                ranked.c.topic_name, ranked.c.platform, ranked.c.topic_id).limit(5)).mappings().all()

    @staticmethod
    def insight(session, project_id, platforms, platform):
        preferred = AIInsight.platform.is_(None) if platform is None else AIInsight.platform == platform
        return session.scalar(select(AIInsight).where(AIInsight.project_id == project_id,
            or_(AIInsight.platform.is_(None), AIInsight.platform.in_(platforms))).order_by(
                case((preferred, 0), else_=1), AIInsight.created_at.desc(), AIInsight.insight_id).limit(1))
