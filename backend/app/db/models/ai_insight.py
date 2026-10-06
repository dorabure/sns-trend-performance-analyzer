import uuid
from datetime import date
from typing import Any

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt


class AIInsight(CreatedAt, Base):
    __tablename__ = "ai_insights"
    insight_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.project_id", ondelete="CASCADE"))
    platform: Mapped[str | None] = mapped_column(String(20))
    analysis_from: Mapped[date] = mapped_column(Date)
    analysis_to: Mapped[date] = mapped_column(Date)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    input_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    model_name: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(30))
    __table_args__ = (
        CheckConstraint("platform IS NULL OR platform IN ('X', 'INSTAGRAM')", name="platform"),
        CheckConstraint("analysis_from <= analysis_to", name="analysis_period"),
    )


Index("idx_ai_insights_project_created", AIInsight.project_id, AIInsight.created_at.desc())
Index("idx_ai_insights_project_period", AIInsight.project_id, AIInsight.analysis_from, AIInsight.analysis_to)
