import uuid
from datetime import date
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, ForeignKey, Index, String, Text, UniqueConstraint, text, true
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, Timestamps


class SNSAccount(Timestamps, Base):
    __tablename__ = "sns_accounts"
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.project_id", ondelete="CASCADE"))
    data_origin: Mapped[str] = mapped_column(String(32), server_default=text("'DEMO_CSV'"))
    provider_connection_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("provider_connections.id", ondelete="SET NULL"))
    platform: Mapped[str] = mapped_column(String(20))
    account_name: Mapped[str] = mapped_column(String(100))
    display_name: Mapped[str | None] = mapped_column(String(200))
    account_role: Mapped[str] = mapped_column(String(20))
    platform_account_id: Mapped[str | None] = mapped_column(String(255))
    profile_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    __table_args__ = (
        CheckConstraint("data_origin IN ('DEMO_CSV', 'X_API', 'INSTAGRAM_API')", name="data_origin"),
        CheckConstraint("platform IN ('X', 'INSTAGRAM')", name="platform"),
        CheckConstraint("account_role IN ('OWN', 'COMPETITOR')", name="account_role"),
        UniqueConstraint("project_id", "platform", "account_name", name="uq_sns_accounts_project_platform_name"),
        Index("uq_sns_accounts_one_own_per_platform", "project_id", "platform", unique=True,
              postgresql_where=text("account_role = 'OWN' AND is_active = TRUE")),
    )


class AccountMetric(CreatedAt, Base):
    __tablename__ = "account_metrics"
    account_metric_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sns_accounts.account_id", ondelete="CASCADE"))
    ingest_key: Mapped[str | None] = mapped_column(String(255))
    ingest_job_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('job_runs.id', ondelete='SET NULL'))
    recorded_date: Mapped[date] = mapped_column(Date)
    followers: Mapped[int | None] = mapped_column(BigInteger)
    following: Mapped[int | None] = mapped_column(BigInteger)
    post_count: Mapped[int | None] = mapped_column(BigInteger)
    raw_metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    __table_args__ = (
        UniqueConstraint("account_id", "recorded_date", name="uq_account_metrics_account_date"),
        Index('uq_account_metrics_ingest_key', 'account_id', 'ingest_key', unique=True, postgresql_where=text('ingest_key IS NOT NULL')),
        *(CheckConstraint(f"{column} IS NULL OR {column} >= 0", name=f"{column}_nonnegative")
          for column in ("followers", "following", "post_count")),
        Index("idx_account_metrics_account_date", "account_id", recorded_date.desc()),
    )
