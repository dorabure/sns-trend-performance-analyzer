import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, Timestamps


class SNSPost(Timestamps, Base):
    __tablename__ = "sns_posts"
    post_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.project_id", ondelete="CASCADE"))
    data_origin: Mapped[str] = mapped_column(String(32), server_default=sql_text("'DEMO_CSV'"))
    provider_connection_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("provider_connections.id", ondelete="SET NULL"))
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sns_accounts.account_id", ondelete="SET NULL"))
    source_type: Mapped[str] = mapped_column(String(20))
    platform: Mapped[str] = mapped_column(String(20))
    platform_post_id: Mapped[str] = mapped_column(String(255))
    author_name: Mapped[str | None] = mapped_column(String(200))
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    text: Mapped[str | None] = mapped_column(Text)
    media_type: Mapped[str | None] = mapped_column(String(30))
    permalink: Mapped[str | None] = mapped_column(Text)
    hashtags: Mapped[list[str]] = mapped_column(JSONB, server_default=sql_text("'[]'::jsonb"))
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    __table_args__ = (
        CheckConstraint("data_origin IN ('DEMO_CSV', 'X_API', 'INSTAGRAM_API')", name="data_origin"),
        CheckConstraint("source_type IN ('OWN', 'COMPETITOR', 'MARKET')", name="source_type"),
        CheckConstraint("platform IN ('X', 'INSTAGRAM')", name="platform"),
        CheckConstraint("media_type IS NULL OR media_type IN ('TEXT', 'IMAGE', 'VIDEO', 'CAROUSEL', 'OTHER')", name="media_type"),
        UniqueConstraint("project_id", "platform", "platform_post_id", name="uq_sns_posts_project_platform_post"),
        Index("idx_sns_posts_project_platform_posted", "project_id", "platform", posted_at.desc()),
        Index("idx_sns_posts_project_source_posted", "project_id", "source_type", posted_at.desc()),
        Index("idx_sns_posts_account_posted", "account_id", posted_at.desc(), postgresql_where=sql_text("account_id IS NOT NULL")),
    )


class PostMetric(CreatedAt, Base):
    __tablename__ = "post_metrics"
    post_metric_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    post_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sns_posts.post_id", ondelete="CASCADE"))
    ingest_key: Mapped[str | None] = mapped_column(String(255))
    ingest_job_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('job_runs.id', ondelete='SET NULL'))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    impressions: Mapped[int | None] = mapped_column(BigInteger)
    reach: Mapped[int | None] = mapped_column(BigInteger)
    views: Mapped[int | None] = mapped_column(BigInteger)
    likes: Mapped[int | None] = mapped_column(BigInteger)
    comments: Mapped[int | None] = mapped_column(BigInteger)
    shares: Mapped[int | None] = mapped_column(BigInteger)
    saves: Mapped[int | None] = mapped_column(BigInteger)
    raw_metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    __table_args__ = (
        UniqueConstraint("post_id", "recorded_at", name="uq_post_metrics_post_recorded"),
        Index('uq_post_metrics_ingest_key', 'post_id', 'ingest_key', unique=True, postgresql_where=sql_text('ingest_key IS NOT NULL')),
        *(CheckConstraint(f"{column} IS NULL OR {column} >= 0", name=f"{column}_nonnegative")
          for column in ("impressions", "reach", "views", "likes", "comments", "shares", "saves")),
        Index("idx_post_metrics_post_recorded", "post_id", recorded_at.desc()),
    )
