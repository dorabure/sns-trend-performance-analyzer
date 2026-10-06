from decimal import Decimal, localcontext

from app.repositories.gap_analysis_repository import GapAnalysisRepository
from app.schemas.gap_analysis import Classification, GapAnalysis, GapItem
from app.services.my_account_service import MyAccountService, number
from app.services.settings_service import SettingsFailure

TREND_THRESHOLD = Decimal('50')
OWN_RATIO_THRESHOLD = Decimal('50')


def ratio(matched, total):
    if not total:
        return None
    with localcontext() as ctx:
        ctx.prec = 50
        return Decimal(matched) / Decimal(total) * 100


def gap_score(trend, own_ratio):
    if trend is None or own_ratio is None:
        return None
    with localcontext() as ctx:
        ctx.prec = 50
        return trend * (1 - own_ratio / 100)


def classify(trend, own_ratio):
    if trend is None or own_ratio is None:
        return None
    if trend >= TREND_THRESHOLD:
        return Classification.OPPORTUNITY if own_ratio < OWN_RATIO_THRESHOLD else Classification.BALANCED
    return Classification.HIGH_COVERAGE if own_ratio >= OWN_RATIO_THRESHOLD else Classification.LOW_PRIORITY


class GapAnalysisService(MyAccountService):
    def __init__(self, session_factory, repository=None):
        super().__init__(session_factory, repository or GapAnalysisRepository())

    def analysis(self, project_id, filters):
        with self.read(project_id) as s:
            return self.analysis_in_session(s, project_id, filters)

    def analysis_in_session(self, s, project_id, filters):
        """Caller owns the consistent read-only snapshot."""
        enabled = self.repository.platforms(s, project_id)
        if filters.platform is not None and filters.platform not in enabled:
            raise SettingsFailure(404, 'NOT_FOUND', 'Platform is not enabled in this Project')
        platforms = enabled if filters.platform is None else [filters.platform]
        topics = self.repository.topics(s, project_id)
        snapshots = {(r['topic_id'], r['platform']): r for r in self.repository.snapshots(s, project_id, platforms, filters)}
        totals, matches = self.repository.coverage(s, project_id, platforms, filters)
        total = {(r['platform'], r['source_type']): r['total_posts'] for r in totals}
        matched = {(r['topic_id'], r['platform'], r['source_type']): r['matched_posts'] for r in matches}
        ranked = []
        for topic in topics:
            for platform in platforms:
                snapshot = snapshots.get((topic['topic_id'], platform))
                trend = snapshot['trend_score'] if snapshot is not None else None
                counts = {role: (matched.get((topic['topic_id'], platform, role), 0), total.get((platform, role), 0))
                          for role in ('OWN', 'COMPETITOR')}
                own, comp = ratio(*counts['OWN']), ratio(*counts['COMPETITOR'])
                gap = gap_score(trend, own)
                item = GapItem(**dict(topic), platform=platform, trend_date=snapshot['trend_date'] if snapshot else None,
                    trend_score=number(trend), own_posts=counts['OWN'][0], own_total_posts=counts['OWN'][1],
                    own_post_ratio=number(own), competitor_posts=counts['COMPETITOR'][0],
                    competitor_total_posts=counts['COMPETITOR'][1], competitor_post_ratio=number(comp),
                    gap_score=number(gap), classification=classify(trend, own))
                # Sort and classify raw Decimal values, never rounded presentation values.
                ranked.append((gap, item))
        ranked.sort(key=lambda pair: (pair[0] is None, -(pair[0] or Decimal(0)),
                                     pair[1].topic_name, pair[1].platform, str(pair[1].topic_id)))
        return GapAnalysis(start=filters.start, end=filters.end, trend_threshold=number(TREND_THRESHOLD),
                           own_ratio_threshold=number(OWN_RATIO_THRESHOLD), items=[item for _, item in ranked])
