import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, Date, ForeignKey, Index, Numeric, SmallInteger, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps


class TrendDaily(Timestamps, Base):
    __tablename__ = "trend_daily"
    trend_daily_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("watch_topics.topic_id", ondelete="CASCADE"))
    term_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("watch_terms.term_id", ondelete="CASCADE"))
    platform: Mapped[str] = mapped_column(String(20))
    trend_date: Mapped[date] = mapped_column(Date)
    window_days: Mapped[int] = mapped_column(SmallInteger, server_default=text("7"))
    post_count: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    engagement_count: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    avg_engagement: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    post_growth_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    engagement_growth_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    acceleration_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    post_growth_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    engagement_growth_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    engagement_level_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    acceleration_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    trend_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    __table_args__ = (
        CheckConstraint("platform IN ('X', 'INSTAGRAM')", name="platform"),
        CheckConstraint("window_days = 7", name="window_days"),
        CheckConstraint("post_count >= 0", name="post_count_nonnegative"),
        CheckConstraint("engagement_count >= 0", name="engagement_count_nonnegative"),
        CheckConstraint("avg_engagement IS NULL OR avg_engagement >= 0", name="avg_engagement_nonnegative"),
        *(CheckConstraint(f"{column} IS NULL OR ({column} >= 0 AND {column} <= 100)", name=f"{column}_range")
          for column in ("post_growth_score", "engagement_growth_score", "engagement_level_score", "acceleration_score", "trend_score")),
        Index("uq_trend_daily_topic_window", "topic_id", "platform", "trend_date", "window_days",
              unique=True, postgresql_where=text("term_id IS NULL")),
        Index("uq_trend_daily_term_window", "term_id", "platform", "trend_date", "window_days",
              unique=True, postgresql_where=text("term_id IS NOT NULL")),
        Index("idx_trend_daily_topic_window_date", "topic_id", "platform", "window_days", trend_date.desc()),
        Index("idx_trend_daily_term_window_date", "term_id", "platform", "window_days", trend_date.desc(), postgresql_where=text("term_id IS NOT NULL")),
        Index("idx_trend_daily_platform_date_score", "platform", trend_date.desc(), trend_score.desc()),
    )
