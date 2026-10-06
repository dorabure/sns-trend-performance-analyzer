from collections import defaultdict
from decimal import Decimal

from app.repositories.competitor_repository import CompetitorRepository
from app.schemas.competitors import AccountAnalytics, Analytics, CompetitorPost, Distribution, TopicAccount, TopicDistribution, TopPosts
from app.services.my_account_service import MyAccountService, average, number
from app.services.settings_service import SettingsFailure


class CompetitorService(MyAccountService):
    def __init__(self, session_factory, repository=None):
        super().__init__(session_factory, repository or CompetitorRepository())

    def scope(self, s, project_id, selected, filters):
        enabled = self.repository.platforms(s, project_id)
        platforms = enabled if filters.platform is None else [filters.platform] if filters.platform in enabled else []
        accounts = self.repository.accounts(s, project_id, selected, platforms)
        competitors = {a["account_id"] for a in accounts if a["role"] == "COMPETITOR"}
        if competitors != set(selected):
            raise SettingsFailure(404, "NOT_FOUND", "Active Competitor was not found in this Project and Platform")
        return accounts

    def analytics(self, project_id, selected, filters):
        with self.read(project_id) as s:
            accounts = self.scope(s, project_id, selected, filters)
            rows = self.repository.period_posts(s, project_id, accounts, filters)
            follower_rows = self.repository.account_followers(s, accounts, filters.end)
            return self.analytics_from_rows(accounts, rows, follower_rows, filters)

    def analytics_from_rows(self, accounts, rows, follower_rows, filters):
        """Shared Phase9 calculation without starting a transaction."""
        grouped = defaultdict(list)
        for row in rows:
            grouped[row["account_id"]].append(self.item(row))
        return self.analytics_from_items(accounts, grouped, follower_rows, filters)

    def analytics_from_items(self, accounts, grouped, follower_rows, filters):
        """Shared calculation; Overview may supply already-read OWN facts."""
        followers = {row["account_id"]: row for row in follower_rows}
        result = []
        for account in accounts:
            posts = grouped.get(account["account_id"], [])
            aggregate = self.aggregate(posts)
            follower = followers.get(account["account_id"])
            averages = {f"avg_{name}": number(average([getattr(p, name) for p in posts]))
                        for name in ("views", "likes", "comments", "shares")}
            result.append(AccountAnalytics(**dict(account), followers=follower["followers"] if follower else None,
                followers_as_of=follower["recorded_date"] if follower else None, posts=len(posts),
                posting_frequency=number(Decimal(len(posts)) / Decimal((filters.end-filters.start).days+1)),
                **averages, avg_engagement=aggregate.avg_engagement,
                avg_engagement_rate=aggregate.avg_engagement_rate, engagement_rate_groups=aggregate.rate_groups))
        return Analytics(accounts=result)

    def topic_distribution(self, project_id, selected, filters):
        with self.read(project_id) as s:
            accounts = self.scope(s, project_id, selected, filters)
            metadata = {a["account_id"]: dict(a) for a in accounts}
            totals, rows = self.repository.distribution(s, project_id, accounts, filters)
            counts = {r["account_id"]: r["total_posts"] for r in totals}
            grouped = {}
            for row in rows:
                topic = grouped.setdefault(row["topic_id"], TopicDistribution(topic_id=row["topic_id"],
                    topic_name=row["topic_name"], accounts=[]))
                total = counts.get(row["account_id"], 0)
                matched = row["matched_posts"] if row["matched_posts"] is not None else 0
                topic.accounts.append(TopicAccount(**metadata[row["account_id"]], total_posts=total,
                    matched_posts=matched, ratio=number(Decimal(matched)/Decimal(total)*100) if total else None))
            order = {a["account_id"]: i for i, a in enumerate(accounts)}
            for topic in grouped.values():
                topic.accounts.sort(key=lambda a: order[a.account_id])
            return Distribution(topics=list(grouped.values()))

    def top_posts(self, project_id, selected, filters, limit):
        with self.read(project_id) as s:
            accounts = [a for a in self.scope(s, project_id, selected, filters) if a["role"] == "COMPETITOR"]
            items = [CompetitorPost(**self.item(row).model_dump(), display_name=row["display_name"])
                     for row in self.repository.period_posts(s, project_id, accounts, filters)]
            items.sort(key=lambda p: str(p.post_id))
            items.sort(key=lambda p: p.posted_at, reverse=True)
            items.sort(key=lambda p: (p.engagement is None, -(p.engagement or 0)))
            return TopPosts(items=items[:limit])
