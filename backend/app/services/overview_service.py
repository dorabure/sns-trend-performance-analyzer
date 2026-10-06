from collections import defaultdict
from datetime import date, timedelta, timezone
from decimal import Decimal, localcontext

from app.repositories.my_account_repository import Filters
from app.repositories.overview_repository import OverviewRepository
from app.schemas.my_account import FollowerValue
from app.schemas.overview import (AISummary, CountKPI, Daily, FollowerPoint, FollowerSeries,
    MetricTrend, Overview, OverviewKPIs, PerformanceTrend, Period, RateKPI, Summary, TrendingTopic, ValuePoint)
from app.services.competitor_service import CompetitorService
from app.services.gap_analysis_service import GapAnalysisService
from app.services.my_account_service import MyAccountService, known_sum, number
from app.services.settings_service import SettingsFailure
from app.services.trend_explorer_service import direction


def count_kpi(current, previous):
    change = current - previous if current is not None and previous is not None else None
    with localcontext() as ctx:
        ctx.prec = 50
        rate = Decimal(change) / Decimal(previous) * 100 if change is not None and previous else None
    return CountKPI(value=current, previous_value=previous, change=change, change_rate=number(rate))


def rate_kpi(current, previous):
    groups = current.rate_groups
    old = previous.rate_groups if previous else []
    # Even a single cohort in each period cannot be compared if its measurement basis changed.
    comparable = len(groups) == len(old) == 1 and (
        groups[0].platform, groups[0].denominator_type) == (old[0].platform, old[0].denominator_type)
    change = number(Decimal(str(current.engagement_rate)) - Decimal(str(previous.engagement_rate))) if comparable else None
    return RateKPI(value=current.engagement_rate, previous_value=previous.engagement_rate if previous else None,
        change_point=change, rate_groups=groups, previous_rate_groups=old)


class OverviewService(MyAccountService):
    def __init__(self, session_factory, repository=None):
        super().__init__(session_factory, repository or OverviewRepository())
        self.own = MyAccountService(session_factory)
        self.competitor = CompetitorService(session_factory)
        self.gap = GapAnalysisService(session_factory)

    def scope(self, s, project_id, filters):
        enabled = self.repository.platforms(s, project_id)
        if filters.platform is not None and filters.platform not in enabled:
            raise SettingsFailure(404, 'NOT_FOUND', 'Platform is not enabled in this Project')
        return enabled if filters.platform is None else [filters.platform]

    def own_periods(self, s, project_id, platforms, filters):
        days = (filters.end - filters.start).days + 1
        previous = Filters(filters.start - timedelta(days=days), filters.start - timedelta(days=1),
                           filters.platform) if (filters.start - date.min).days >= days else None
        combined = Filters(previous.start if previous else filters.start, filters.end, filters.platform)
        items = [self.own.analytics_item(r) for r in self.own.repository.posts(s, project_id, platforms, combined, lean=True)]
        current_items = [p for p in items if p.posted_at.astimezone(timezone.utc).date() >= filters.start]
        followers = [FollowerValue(**r) for r in self.repository.followers(s, project_id, platforms, filters.end)]
        current = self.own.kpis(current_items, followers)
        old = None
        if previous:
            previous_followers = [FollowerValue(**r) for r in self.repository.followers(s, project_id, platforms, previous.end)]
            old = self.own.kpis([p for p in items if p.posted_at.astimezone(timezone.utc).date() < filters.start], previous_followers)
        return current_items, current, old, previous

    def performance(self, s, project_id, platforms, filters, items, followers):
        days = [filters.start + timedelta(days=i) for i in range((filters.end - filters.start).days + 1)]
        grouped = defaultdict(list)
        for p in items:
            grouped[p.posted_at.astimezone(timezone.utc).date()].append(p)
        daily = [Daily(date=day, posts=len(grouped[day]), reach=known_sum([p.reach for p in grouped[day]]),
            engagement=self.own.aggregate(grouped[day]).engagement_total) for day in days]
        history = {(r['account_id'], r['recorded_date']): r['followers']
                   for r in self.repository.follower_history(s, project_id, platforms, filters)}
        series = [FollowerSeries(account_id=a.account_id, account_name=a.account_name, platform=a.platform,
            values=[FollowerPoint(date=day, followers=history.get((a.account_id, day)),
                row_present=(a.account_id, day) in history) for day in days]) for a in followers]
        return PerformanceTrend(daily=daily, follower_series=series)

    def summary(self, items, accounts, follower_rows):
        aggregate = self.own.aggregate(items)
        follower_map = {r['account_id']: r for r in follower_rows}
        followers = [FollowerValue(platform=a['platform'], account_id=a['account_id'], account_name=a['account_name'],
            recorded_date=follower_map.get(a['account_id'], {}).get('recorded_date'),
            followers=follower_map.get(a['account_id'], {}).get('followers')) for a in accounts]
        return Summary(posts=len(items), avg_engagement=aggregate.avg_engagement,
            avg_engagement_rate=aggregate.avg_engagement_rate, rate_groups=aggregate.rate_groups,
            followers_by_account=followers, account_count=len(accounts))

    def overview(self, project_id, filters):
        # Only this context starts a transaction; all section helpers share this Session.
        with self.read(project_id) as s:
            return self.overview_in_session(s, project_id, filters)

    def overview_in_session(self, s, project_id, filters):
        platforms = self.scope(s, project_id, filters)
        items, current, old, previous = self.own_periods(s, project_id, platforms, filters)
        fields = {name: count_kpi(getattr(current, name), getattr(old, name) if old else None)
                  for name in ('reach', 'posts', 'impressions', 'engagement', 'followers')}
        # Account identity must agree when comparing followers.
        if old and [a.account_id for a in current.followers_by_account] != [a.account_id for a in old.followers_by_account]:
            fields['followers'] = count_kpi(current.followers, None)
        kpis = OverviewKPIs(**fields, engagement_rate=rate_kpi(current, old),
                            followers_by_account=current.followers_by_account)
        performance = self.performance(s, project_id, platforms, filters, items, current.followers_by_account)
        accounts = self.repository.accounts(s, project_id, platforms)
        competitor_accounts = [a for a in accounts if a['role'] == 'COMPETITOR']
        own_accounts = [a for a in accounts if a['role'] == 'OWN']
        rows = self.competitor.repository.period_posts(s, project_id, competitor_accounts, filters)
        follower_rows = self.competitor.repository.account_followers(s, accounts, filters.end)
        own_platforms = {a['account_id']: a['platform'] for a in own_accounts}
        # KPI history includes inactive/inconsistent OWN rows; account summaries
        # must retain the competitor repository's active role/platform contract.
        own_items = [p for p in items if own_platforms.get(p.account_id) == p.platform]
        competitor_items = [self.own.item(r) for r in rows]
        grouped = defaultdict(list)
        for p in own_items + competitor_items:
            grouped[p.account_id].append(p)
        account_results = self.competitor.analytics_from_items(accounts, grouped, follower_rows, filters)
        # Repository order is name/platform/UUID, not a performance ranking.
        top_accounts = [a for a in account_results.accounts if a.role == 'COMPETITOR'][:3]
        gap = self.gap.analysis_in_session(s, project_id, filters)
        opportunity = next((a for a in gap.items if a.gap_score is not None), None)
        trends = [TrendingTopic(**r, trend_direction=direction(r['post_growth_rate']))
                  for r in self.repository.top_trends(s, project_id, platforms, filters)]
        insight = self.repository.insight(s, project_id, platforms, filters.platform)
        return Overview(period=Period(start=filters.start, end=filters.end),
            previous_period=Period(start=previous.start, end=previous.end) if previous else None,
            kpis=kpis, performance_trend=performance, top_trends=trends,
            competitor_summary=top_accounts, own_summary=self.summary(own_items, own_accounts, follower_rows),
            competitor_aggregate=self.summary(competitor_items, competitor_accounts, follower_rows),
            top_opportunity=opportunity, ai_summary=AISummary.model_validate(insight) if insight else None)

    def performance_trend(self, project_id, filters, metric):
        with self.read(project_id) as s:
            platforms = self.scope(s, project_id, filters)
            items = [self.own.analytics_item(r) for r in self.own.repository.posts(s, project_id, platforms, filters, lean=True)]
            followers = [FollowerValue(**r) for r in self.repository.followers(s, project_id, platforms, filters.end)]
            performance = self.performance(s, project_id, platforms, filters, items, followers)
            return MetricTrend(metric=metric,
                series=[] if metric == 'followers' else [ValuePoint(date=d.date, value=getattr(d, metric)) for d in performance.daily],
                follower_series=performance.follower_series if metric == 'followers' else [])
