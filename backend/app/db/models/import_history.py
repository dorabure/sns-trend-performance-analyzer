import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ImportHistory(Base):
    __tablename__ = "import_histories"
    import_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.project_id", ondelete="CASCADE"))
    job_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('job_runs.id', ondelete='SET NULL'))
    data_origin: Mapped[str] = mapped_column(String(32), server_default=text("'DEMO_CSV'"))
    provider_connection_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('provider_connections.id', ondelete='SET NULL'))
    import_type: Mapped[str] = mapped_column(String(30))
    filename: Mapped[str] = mapped_column(String(255))
    total_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    success_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    error_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    status: Mapped[str] = mapped_column(String(20))
    error_detail: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp())
    __table_args__ = (
        CheckConstraint("data_origin IN ('DEMO_CSV', 'X_API', 'INSTAGRAM_API')", name='data_origin'),
        Index('idx_import_histories_provider_connection_id', 'provider_connection_id'),
        Index('idx_import_histories_job_run_id', 'job_run_id'),
        CheckConstraint("import_type IN ('OWN_POSTS', 'ACCOUNT_DAILY', 'TREND_POSTS', 'COMPETITOR_POSTS')", name="import_type"),
        CheckConstraint("status IN ('PROCESSING', 'SUCCESS', 'PARTIAL_ERROR', 'FAILED')", name="status"),
        *(CheckConstraint(f"{column} >= 0", name=f"{column}_nonnegative") for column in ("total_count", "success_count", "error_count")),
        Index("idx_import_histories_project_imported", "project_id", imported_at.desc()),
    )
