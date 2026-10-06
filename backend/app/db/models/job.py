"""PostgreSQL is the sole business job state store."""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, event, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.core.provider_metadata import safe_metadata
from app.db.base import Base, Timestamps

STATUSES = ('PENDING', 'RUNNING', 'SUCCESS', 'PARTIAL_ERROR', 'FAILED', 'SKIPPED', 'CANCELED')
ACTIVE = frozenset(('PENDING', 'RUNNING'))
TERMINAL = frozenset(STATUSES) - ACTIVE
PIPELINE = ('PROVIDER_SYNC', 'NORMALIZE_IMPORT', 'TREND_REBUILD', 'AI_INSIGHT_GENERATE')


class JobFields(Timestamps):
    status: Mapped[str] = mapped_column(String(32), server_default=text("'PENDING'"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    record_count: Mapped[int] = mapped_column(Integer, server_default=text('0'))
    error_count: Mapped[int] = mapped_column(Integer, server_default=text('0'))
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_summary: Mapped[str | None] = mapped_column(String(1000))
    result_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))

    @validates('error_code', 'error_summary', 'result_summary')
    def validate_metadata(self, key, value):
        return safe_metadata(value)


class JobRun(JobFields, Base):
    __tablename__ = 'job_runs'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('projects.project_id', ondelete='CASCADE'))
    data_mode: Mapped[str] = mapped_column(String(16))
    provider_connection_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('provider_connections.id', ondelete='SET NULL'))
    job_type: Mapped[str] = mapped_column(String(32))
    job_schedule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('job_schedules.id', ondelete='SET NULL'))
    trigger_type: Mapped[str] = mapped_column(String(16), server_default=text("'SYSTEM'"))
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("trigger_type IN ('MANUAL', 'SCHEDULED', 'SYSTEM')", name='trigger_type'),
        CheckConstraint("data_mode IN ('DEMO', 'LIVE')", name='data_mode'),
        CheckConstraint("job_type = 'PROVIDER_SYNC'", name='job_type'),
        CheckConstraint(f'status IN {STATUSES}', name='status'),
        *(CheckConstraint(f'{c} >= 0', name=f'{c}_nonnegative') for c in ('record_count', 'error_count')),
        Index('uq_job_runs_active_scope', 'project_id', 'data_mode', 'provider_connection_id', 'job_type',
              unique=True, postgresql_nulls_not_distinct=True, postgresql_where=text("status IN ('PENDING', 'RUNNING')")),
    )


class JobStep(JobFields, Base):
    __tablename__ = 'job_steps'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('job_runs.id', ondelete='CASCADE'))
    step_type: Mapped[str] = mapped_column(String(32))
    sequence_no: Mapped[int] = mapped_column(Integer)
    attempt_count: Mapped[int] = mapped_column(Integer, server_default=text('0'))
    __table_args__ = (
        CheckConstraint(f'status IN {STATUSES}', name='status'),
        CheckConstraint(f'step_type IN {PIPELINE}', name='step_type'),
        CheckConstraint('sequence_no > 0', name='sequence_positive'),
        *(CheckConstraint(f'{c} >= 0', name=f'{c}_nonnegative') for c in ('attempt_count', 'record_count', 'error_count')),
        UniqueConstraint('job_run_id', 'step_type', name='uq_job_steps_run_type'),
        UniqueConstraint('job_run_id', 'sequence_no', name='uq_job_steps_run_sequence'),
    )


@event.listens_for(JobRun, 'before_insert')
@event.listens_for(JobRun, 'before_update')
@event.listens_for(JobStep, 'before_insert')
@event.listens_for(JobStep, 'before_update')
def validate_job_metadata(mapper, connection, target):
    for value in (target.error_code, target.error_summary, target.result_summary):
        safe_metadata(value)
