"""MARKET-only UTC rolling trends, rebuilt in the caller's transaction."""
from collections import defaultdict
from datetime import timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Project
from app.repositories.trend_repository import TrendInputs, TrendRepository
from app.services.trend_calculation import (RAW_QUANTUM, WindowAggregate, calculate_acceleration,
    calculate_engagement, calculate_engagement_growth, calculate_growth_rate,
    calculate_trend_score, normalize_scores, rounded)

COMPONENTS = {"post_growth_rate": "post_growth_score", "engagement_growth_rate": "engagement_growth_score",
              "avg_engagement": "engagement_level_score", "acceleration_rate": "acceleration_score"}


def build_trend_rows(inputs: TrendInputs) -> list[dict]:
    if not inputs.posts or not inputs.platforms or not inputs.topics:
        return []
    facts = {post.post_id: post for post in inputs.posts}
    dates = {post.post_id: post.posted_at.astimezone(timezone.utc).date() for post in inputs.posts}
    first, last = min(dates.values()), max(dates.values())
    day_count = (last - first).days + 1
    # Sparse daily buckets then prefix sums: O(post links + dates * grains).
    buckets = defaultdict(dict)
    for links, is_term in ((inputs.topic_links, False), (inputs.term_links, True)):
        for post_id, target_id in set(links):
            post = facts[post_id]
            if post.platform not in inputs.platforms:
                continue
            topic_id = inputs.terms[target_id] if is_term else target_id
            key = (post.platform, topic_id, target_id if is_term else None)
            index = (dates[post_id] - first).days + 20
            bucket = buckets[key].setdefault(index, [0, 0, 0])
            engagement = calculate_engagement(post.likes, post.comments, post.shares, post.saves)
            bucket[0] += 1
            if engagement is not None:
                bucket[1] += engagement
                bucket[2] += 1
    grains = [(topic_id, None) for topic_id in inputs.topics] + [(topic_id, term_id) for term_id, topic_id in inputs.terms.items()]
    rows = []
    cohorts = defaultdict(list)
    for platform in inputs.platforms:
        for topic_id, term_id in grains:
            daily = buckets[(platform, topic_id, term_id)]
            prefix = [(0, 0, 0)]
            for index in range(day_count + 20):
                counts = daily.get(index, (0, 0, 0))
                prefix.append(tuple(a + b for a, b in zip(prefix[-1], counts)))
            def window(start, end):
                return WindowAggregate(*(a - b for a, b in zip(prefix[end], prefix[start])))
            for day in range(day_count):
                end = day + 21
                current = window(end - 7, end)
                previous = window(end - 14, end - 7)
                prior = window(end - 21, end - 14)
                growth = calculate_growth_rate(current.post_count, previous.post_count)
                row = dict(topic_id=topic_id, term_id=term_id, platform=platform,
                           trend_date=first + timedelta(days=day), window_days=7,
                           post_count=current.post_count, engagement_count=current.engagement_count,
                           avg_engagement=current.avg_engagement, post_growth_rate=growth,
                           engagement_growth_rate=calculate_engagement_growth(current, previous),
                           acceleration_rate=calculate_acceleration(growth,
                               calculate_growth_rate(previous.post_count, prior.post_count)))
                rows.append(row)
                cohorts[(platform, row["trend_date"], 7, "TERM" if term_id else "TOPIC")].append(row)
    for cohort in cohorts.values():
        for raw, score in COMPONENTS.items():
            for row, value in zip(cohort, normalize_scores([row[raw] for row in cohort])):
                row[score] = value
        for row in cohort:
            row["trend_score"] = calculate_trend_score(*(row[score] for score in COMPONENTS.values()))
            for raw in COMPONENTS:
                row[raw] = rounded(row[raw], RAW_QUANTUM)
    return rows


class TrendService:
    def __init__(self, repository: TrendRepository | None = None):
        self.repository = repository if repository is not None else TrendRepository()

    def rebuild_project(self, session: Session, project_id: UUID) -> int:
        # Also serialize explicit service callers. Reentrant with ImportService's lock.
        project = session.scalar(select(Project.project_id).where(Project.project_id == project_id).with_for_update())
        if project is None:
            raise ValueError("Project was not found")
        rows = build_trend_rows(self.repository.load(session, project_id))
        self.repository.replace(session, project_id, rows)
        return len(rows)
