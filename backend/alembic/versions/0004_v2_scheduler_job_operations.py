"""Database schedules and durable dispatch metadata."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0004_v2_scheduler_ops'
down_revision = '0003_v2_background_jobs'
branch_labels = depends_on = None


def upgrade():
    op.create_table('job_schedules',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.project_id', ondelete='CASCADE'), nullable=False),
        sa.Column('provider_connection_id', UUID(as_uuid=True), sa.ForeignKey('provider_connections.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('schedule_type', sa.String(64), nullable=False, server_default='PROVIDER_SYNC_PIPELINE'),
        sa.Column('schedule_mode', sa.String(16), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('interval_seconds', sa.Integer()), sa.Column('daily_time', sa.Time()), sa.Column('timezone', sa.String(64)),
        sa.Column('next_run_at', sa.DateTime(timezone=True)), sa.Column('last_run_at', sa.DateTime(timezone=True)),
        sa.Column('last_job_run_id', UUID(as_uuid=True)),
        sa.Column('schedule_scope_key', sa.String(255), nullable=False, unique=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.CheckConstraint("schedule_type = 'PROVIDER_SYNC_PIPELINE'", name='schedule_type'),
        sa.CheckConstraint("(schedule_mode = 'INTERVAL' AND interval_seconds >= 60 AND interval_seconds IS NOT NULL AND daily_time IS NULL) OR (schedule_mode = 'DAILY' AND interval_seconds IS NULL AND daily_time IS NOT NULL AND timezone IS NOT NULL)", name='schedule_fields'))
    op.create_index('idx_job_schedules_due', 'job_schedules', ['next_run_at'], postgresql_where=sa.text('enabled = true AND next_run_at IS NOT NULL'))
    op.add_column('job_runs', sa.Column('job_schedule_id', UUID(as_uuid=True)))
    op.add_column('job_runs', sa.Column('trigger_type', sa.String(16), nullable=False, server_default='SYSTEM'))
    op.add_column('job_runs', sa.Column('scheduled_for', sa.DateTime(timezone=True)))
    op.add_column('job_runs', sa.Column('enqueued_at', sa.DateTime(timezone=True)))
    op.create_foreign_key('fk_job_runs_job_schedule_id_job_schedules', 'job_runs', 'job_schedules', ['job_schedule_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_job_schedules_last_job_run_id_job_runs', 'job_schedules', 'job_runs', ['last_job_run_id'], ['id'], ondelete='SET NULL')
    op.create_check_constraint('trigger_type', 'job_runs', "trigger_type IN ('MANUAL', 'SCHEDULED', 'SYSTEM')")


def downgrade():
    op.drop_constraint('fk_job_schedules_last_job_run_id_job_runs', 'job_schedules', type_='foreignkey')
    op.drop_constraint('fk_job_runs_job_schedule_id_job_schedules', 'job_runs', type_='foreignkey')
    op.drop_constraint(op.f('ck_job_runs_trigger_type'), 'job_runs', type_='check')
    for column in ('enqueued_at', 'scheduled_for', 'trigger_type', 'job_schedule_id'):
        op.drop_column('job_runs', column)
    op.drop_table('job_schedules')
