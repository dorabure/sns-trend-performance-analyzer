import uuid
from datetime import datetime, time
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Time, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, Timestamps


class JobSchedule(Timestamps, Base):
    __tablename__ = 'job_schedules'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('projects.project_id', ondelete='CASCADE'))
    provider_connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('provider_connections.id', ondelete='RESTRICT'))
    schedule_type: Mapped[str] = mapped_column(String(64), server_default=text("'PROVIDER_SYNC_PIPELINE'"))
    schedule_mode: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text('false'))
    interval_seconds: Mapped[int | None] = mapped_column(Integer)
    daily_time: Mapped[time | None] = mapped_column(Time)
    timezone: Mapped[str | None] = mapped_column(String(64))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_job_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('job_runs.id', ondelete='SET NULL', use_alter=True))
    schedule_scope_key: Mapped[str] = mapped_column(String(255), unique=True)
    __table_args__ = (
        CheckConstraint("schedule_type = 'PROVIDER_SYNC_PIPELINE'", name='schedule_type'),
        CheckConstraint("(schedule_mode = 'INTERVAL' AND interval_seconds >= 60 AND interval_seconds IS NOT NULL AND daily_time IS NULL) OR (schedule_mode = 'DAILY' AND interval_seconds IS NULL AND daily_time IS NOT NULL AND timezone IS NOT NULL)", name='schedule_fields'),
        Index('idx_job_schedules_due', 'next_run_at', postgresql_where=text('enabled = true AND next_run_at IS NOT NULL')),
    )
