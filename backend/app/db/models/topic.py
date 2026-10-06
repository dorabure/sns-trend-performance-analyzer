import uuid
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, true
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, Timestamps


class WatchTopic(Timestamps, Base):
    __tablename__ = "watch_topics"
    topic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.project_id", ondelete="CASCADE"))
    topic_name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    __table_args__ = (UniqueConstraint("project_id", "topic_name", name="uq_watch_topics_project_name"),)


class WatchTerm(CreatedAt, Base):
    __tablename__ = "watch_terms"
    term_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("watch_topics.topic_id", ondelete="CASCADE"))
    term: Mapped[str] = mapped_column(String(255))
    normalized_term: Mapped[str] = mapped_column(String(255))
    term_type: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    __table_args__ = (
        CheckConstraint("term_type IN ('KEYWORD', 'HASHTAG')", name="term_type"),
        UniqueConstraint("topic_id", "term_type", "normalized_term", name="uq_watch_terms_topic_type_normalized"),
    )


class PostTopic(CreatedAt, Base):
    __tablename__ = "post_topics"
    post_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sns_posts.post_id", ondelete="CASCADE"), primary_key=True)
    topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("watch_topics.topic_id", ondelete="CASCADE"), primary_key=True)
    match_type: Mapped[str] = mapped_column(String(20))
    match_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    __table_args__ = (
        CheckConstraint("match_type IN ('KEYWORD', 'HASHTAG', 'AI', 'MANUAL')", name="match_type"),
        CheckConstraint("match_score IS NULL OR (match_score >= 0 AND match_score <= 100)", name="match_score_range"),
        Index("idx_post_topics_topic_post", "topic_id", "post_id"),
    )


class PostTerm(CreatedAt, Base):
    __tablename__ = "post_terms"
    post_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sns_posts.post_id", ondelete="CASCADE"), primary_key=True)
    term_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("watch_terms.term_id", ondelete="CASCADE"), primary_key=True)
    match_method: Mapped[str] = mapped_column(String(20))
    match_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    __table_args__ = (
        CheckConstraint("match_method IN ('EXACT', 'NORMALIZED', 'MANUAL', 'AI')", name="match_method"),
        CheckConstraint("match_score IS NULL OR (match_score >= 0 AND match_score <= 100)", name="match_score_range"),
        Index("idx_post_terms_term_post", "term_id", "post_id"),
    )
