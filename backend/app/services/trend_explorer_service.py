from datetime import timedelta

from app.repositories.trend_explorer_repository import TrendExplorerRepository
from app.schemas.trends import Point, Ranking, RankingItem, Series, Timeseries, TopPosts
from app.services.matching_service import normalize_term
from app.services.my_account_service import MyAccountService
from app.services.settings_service import SettingsFailure


def direction(growth):
    return "UNKNOWN" if growth is None else "UP" if growth > 0 else "DOWN" if growth < 0 else "FLAT"


class TrendExplorerService(MyAccountService):
    def __init__(self, session_factory, repository=None):
        super().__init__(session_factory, repository or TrendExplorerRepository())

    def scope(self, s, project_id, filters, topic_id=None, term_ids=None):
        if topic_id is not None:
            topic = self.repository.topic(s, project_id, topic_id)
            if topic is None or not topic.is_active:
                raise SettingsFailure(404, "NOT_FOUND", "Active Topic was not found")
        terms = self.repository.terms(s, project_id, topic_id, term_ids)
        if term_ids is not None and {t["term_id"] for t in terms} != set(term_ids):
            raise SettingsFailure(404, "NOT_FOUND", "Active Term was not found in this scope")
        enabled = self.repository.platforms(s, project_id)
        platforms = enabled if not filters.platform else [filters.platform] if filters.platform in enabled else []
        if filters.keyword:
            key = normalize_term(filters.keyword)
            terms = [t for t in terms if key in normalize_term(t["term"])]
        return terms, platforms

    def ranking(self, project_id, topic_id, filters, limit):
        with self.read(project_id) as s:
            terms, platforms = self.scope(s, project_id, filters, topic_id)
            metadata = {t["term_id"]: t for t in terms}
            rows = self.repository.snapshots(s, project_id, terms, platforms, filters, latest=True)
            rows.sort(key=lambda r: (r["trend_score"] is None, -(r["trend_score"] or 0),
                                    metadata[r["term_id"]]["term"], str(r["term_id"]), r["platform"]))
            as_of = max((r["trend_date"] for r in rows), default=None)
            items = [RankingItem(**dict(r), **{k: v for k, v in metadata[r["term_id"]].items() if k not in ("term_id", "term")},
                                 keyword=metadata[r["term_id"]]["term"], trend_direction=direction(r["post_growth_rate"]))
                     for r in rows[:limit]]
            return Ranking(score_as_of=as_of, items=items)

    def timeseries(self, project_id, term_ids, filters, metric):
        with self.read(project_id) as s:
            terms, platforms = self.scope(s, project_id, filters, term_ids=term_ids)
            rows = self.repository.snapshots(s, project_id, terms, platforms, filters)
            lookup = {(r["term_id"], r["platform"], r["trend_date"]): r for r in rows}
            column = "engagement_count" if metric == "engagement" else metric
            dates = [filters.start + timedelta(days=d) for d in range((filters.end - filters.start).days + 1)]
            series = []
            for term in terms:
                for platform in sorted(platforms):
                    values = []
                    for day in dates:
                        row = lookup.get((term["term_id"], platform, day))
                        values.append(Point(date=day, value=row[column] if row is not None else None,
                                            row_present=row is not None))
                    series.append(Series(**dict(term), term_name=term["term"], platform=platform, values=values))
            return Timeseries(metric=metric, series=series)

    def top_posts(self, project_id, topic_id, filters, limit, term_id=None):
        with self.read(project_id) as s:
            terms, platforms = self.scope(s, project_id, filters, topic_id, [term_id] if term_id else None)
            # Keyword applies to WatchTerm, then its existing matches (not raw post-text guessing).
            linked_terms = [t["term_id"] for t in terms] if term_id or filters.keyword else None
            rows = self.repository.popular(s, project_id, topic_id, platforms, filters, linked_terms)
            items = [self.item(r) for r in rows]
            items.sort(key=lambda p: str(p.post_id))
            items.sort(key=lambda p: p.posted_at, reverse=True)
            items.sort(key=lambda p: (p.engagement is None, -(p.engagement or 0)))
            return TopPosts(items=items[:limit])
