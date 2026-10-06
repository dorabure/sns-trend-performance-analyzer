"""Bulk reads scoped by Account role, Project, Platform and UTC period."""
from datetime import datetime, time, timezone

from sqlalchemy import and_, func, or_, select, true

from app.db.models import AccountMetric, PostMetric, PostTopic, SNSAccount, SNSPost, WatchTopic
from app.repositories.my_account_repository import METRICS, MyAccountRepository


class CompetitorRepository(MyAccountRepository):
    @staticmethod
    def accounts(session, project_id, selected, platforms):
        return session.execute(select(SNSAccount.account_id, SNSAccount.account_name, SNSAccount.display_name,
            SNSAccount.platform, SNSAccount.account_role.label("role")).where(
                SNSAccount.project_id == project_id, SNSAccount.is_active.is_(True),
                SNSAccount.platform.in_(platforms),
                or_(SNSAccount.account_role == "OWN", SNSAccount.account_id.in_(selected)))
            .order_by(SNSAccount.account_role.desc(), SNSAccount.platform, SNSAccount.account_name, SNSAccount.account_id))\
            .mappings().all()

    @staticmethod
    def scope_query(project_id, accounts, filters):
        # Account role/source and platform must agree even for inconsistent legacy rows.
        return select(SNSPost.post_id, SNSPost.account_id).join(SNSAccount, and_(
            SNSAccount.account_id == SNSPost.account_id, SNSAccount.project_id == SNSPost.project_id,
            SNSAccount.platform == SNSPost.platform, SNSAccount.account_role == SNSPost.source_type)).where(
                SNSPost.project_id == project_id, SNSPost.account_id.in_([a["account_id"] for a in accounts]),
                SNSAccount.is_active.is_(True), SNSPost.source_type.in_(["OWN", "COMPETITOR"]),
                SNSPost.posted_at >= datetime.combine(filters.start, time.min, timezone.utc),
                SNSPost.posted_at <= datetime.combine(filters.end, time.max, timezone.utc))

    def period_posts(self, session, project_id, accounts, filters):
        scoped = self.scope_query(project_id, accounts, filters).cte("competitor_period_posts").prefix_with("MATERIALIZED")
        latest = self.latest_metric(SNSPost.post_id)
        return session.execute(select(SNSPost.post_id, SNSPost.account_id, SNSPost.author_name,
            SNSPost.platform, SNSPost.posted_at, SNSPost.text, SNSPost.media_type, SNSPost.permalink,
            SNSPost.hashtags, SNSAccount.account_name, SNSAccount.display_name, latest.c.recorded_at,
            *(latest.c[n] for n in METRICS)).join(scoped, scoped.c.post_id == SNSPost.post_id)
            .join(SNSAccount, SNSAccount.account_id == SNSPost.account_id)
            .outerjoin(latest, true())).mappings().all()

    @staticmethod
    def account_followers(session, accounts, end):
        latest = select(AccountMetric.account_id, AccountMetric.recorded_date, AccountMetric.followers,
            func.row_number().over(partition_by=AccountMetric.account_id,
                order_by=AccountMetric.recorded_date.desc()).label("position")).where(
                    AccountMetric.account_id.in_([a["account_id"] for a in accounts]),
                    AccountMetric.recorded_date <= end).subquery()
        return session.execute(select(latest).where(latest.c.position == 1)).mappings().all()

    def distribution(self, session, project_id, accounts, filters):
        scoped = self.scope_query(project_id, accounts, filters).cte("distribution_posts").prefix_with("MATERIALIZED")
        totals = select(scoped.c.account_id, func.count(scoped.c.post_id).label("total_posts"))\
            .group_by(scoped.c.account_id).subquery()
        matched = select(scoped.c.account_id, PostTopic.topic_id,
            func.count(func.distinct(scoped.c.post_id)).label("matched_posts"))\
            .join(PostTopic, PostTopic.post_id == scoped.c.post_id).join(WatchTopic, WatchTopic.topic_id == PostTopic.topic_id)\
            .where(WatchTopic.project_id == project_id, WatchTopic.is_active.is_(True))\
            .group_by(scoped.c.account_id, PostTopic.topic_id).subquery()
        # One bulk query for totals, one for every Topic × Account (including 0 matches).
        total_rows = session.execute(select(totals)).mappings().all()
        rows = session.execute(select(WatchTopic.topic_id, WatchTopic.topic_name, SNSAccount.account_id,
            matched.c.matched_posts).join(SNSAccount, SNSAccount.project_id == WatchTopic.project_id)
            .outerjoin(matched, and_(matched.c.topic_id == WatchTopic.topic_id,
                                   matched.c.account_id == SNSAccount.account_id)).where(
                WatchTopic.project_id == project_id, WatchTopic.is_active.is_(True),
                SNSAccount.account_id.in_([a["account_id"] for a in accounts]))
            .order_by(WatchTopic.topic_name, WatchTopic.topic_id, SNSAccount.account_id)).mappings().all()
        return total_rows, rows
