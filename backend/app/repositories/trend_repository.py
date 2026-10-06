"""Bulk Trend inputs and project-scoped materialization. Never commits."""
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, insert, select, true
from sqlalchemy.orm import Session

from app.db.models import PostMetric, PostTerm, PostTopic, ProjectPlatform, SNSPost, TrendDaily, WatchTerm, WatchTopic


@dataclass(frozen=True)
class MarketFact:
    post_id: UUID
    platform: str
    posted_at: datetime
    likes: int | None
    comments: int | None
    shares: int | None
    saves: int | None


@dataclass(frozen=True)
class TrendInputs:
    platforms: list[str]
    topics: list[UUID]
    terms: dict[UUID, UUID]  # term_id -> parent topic_id
    posts: list[MarketFact]
    topic_links: list[tuple[UUID, UUID]]  # post_id, topic_id
    term_links: list[tuple[UUID, UUID]]  # post_id, term_id


class TrendRepository:
    def load(self, session: Session, project_id: UUID) -> TrendInputs:
        platforms = list(session.scalars(select(ProjectPlatform.platform).where(ProjectPlatform.project_id == project_id)))
        topics = list(session.scalars(select(WatchTopic.topic_id).where(
            WatchTopic.project_id == project_id, WatchTopic.is_active.is_(True))))
        terms = dict(session.execute(select(WatchTerm.term_id, WatchTerm.topic_id).join(WatchTopic).where(
            WatchTopic.project_id == project_id, WatchTopic.is_active.is_(True), WatchTerm.is_active.is_(True))).all())
        # Read one indexed snapshot per outer post. A global window subquery can
        # be rescanned for every post when fresh import statistics underestimate
        # MARKET rows, exceeding the production session's statement timeout.
        latest = select(PostMetric.likes, PostMetric.comments, PostMetric.shares, PostMetric.saves).where(
            PostMetric.post_id == SNSPost.post_id).order_by(
                PostMetric.recorded_at.desc()).limit(1).correlate(SNSPost).lateral()
        rows = session.execute(select(SNSPost.post_id, SNSPost.platform, SNSPost.posted_at,
                                      latest.c.likes, latest.c.comments, latest.c.shares, latest.c.saves).outerjoin(
            latest, true()).where(
                SNSPost.project_id == project_id, SNSPost.source_type == "MARKET")).all()
        posts = [MarketFact(*row) for row in rows]
        topic_links = session.execute(select(PostTopic.post_id, PostTopic.topic_id).join(
            SNSPost, SNSPost.post_id == PostTopic.post_id).join(WatchTopic).where(
                SNSPost.project_id == project_id, SNSPost.source_type == "MARKET",
                WatchTopic.project_id == project_id, WatchTopic.is_active.is_(True))).all()
        term_links = session.execute(select(PostTerm.post_id, PostTerm.term_id).join(
            SNSPost, SNSPost.post_id == PostTerm.post_id).join(WatchTerm).join(WatchTopic).where(
                SNSPost.project_id == project_id, SNSPost.source_type == "MARKET",
                WatchTopic.project_id == project_id, WatchTopic.is_active.is_(True), WatchTerm.is_active.is_(True))).all()
        return TrendInputs(platforms, topics, terms, posts, topic_links, term_links)

    def replace(self, session: Session, project_id: UUID, rows: list[dict]) -> None:
        session.execute(delete(TrendDaily).where(TrendDaily.topic_id.in_(
            select(WatchTopic.topic_id).where(WatchTopic.project_id == project_id))))
        # Bound statement size; no per-row SELECT or COMMIT.
        for offset in range(0, len(rows), 1000):
            session.execute(insert(TrendDaily), rows[offset:offset + 1000])
