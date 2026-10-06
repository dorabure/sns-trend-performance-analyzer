"""Background job foundation; retain legacy CSV metric identities."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# Alembic's existing version_num is VARCHAR(32); the descriptive filename is longer.
revision = '0003_v2_background_jobs'
down_revision = '0002_v2_data_mode_and_providers'
branch_labels = None
depends_on = None

STATUSES = "('PENDING', 'RUNNING', 'SUCCESS', 'PARTIAL_ERROR', 'FAILED', 'SKIPPED', 'CANCELED')"


def common_columns():
    return [
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('status', sa.String(32), server_default=sa.text("'PENDING'"), nullable=False),
        *[sa.Column(n, sa.DateTime(timezone=True), nullable=True) for n in ('started_at', 'finished_at')],
        *[sa.Column(n, sa.Integer(), server_default=sa.text('0'), nullable=False) for n in ('record_count', 'error_count')],
        sa.Column('error_code', sa.String(128), nullable=True),
        sa.Column('error_summary', sa.String(1000), nullable=True),
        sa.Column('result_summary', JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        *[sa.Column(n, sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False) for n in ('created_at', 'updated_at')],
    ]


def checks(table, counters):
    return [sa.CheckConstraint(f'status IN {STATUSES}', name=op.f(f'ck_{table}_status')),
            *[sa.CheckConstraint(f'{n} >= 0', name=op.f(f'ck_{table}_{n}_nonnegative')) for n in counters]]


def upgrade():
    op.create_table('job_runs', *common_columns(),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('data_mode', sa.String(16), nullable=False),
        sa.Column('provider_connection_id', sa.UUID(), nullable=True),
        sa.Column('job_type', sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_job_runs')),
        sa.ForeignKeyConstraint(['project_id'], ['projects.project_id'], ondelete='CASCADE', name=op.f('fk_job_runs_project_id_projects')),
        sa.ForeignKeyConstraint(['provider_connection_id'], ['provider_connections.id'], ondelete='SET NULL', name=op.f('fk_job_runs_provider_connection_id_provider_connections')),
        sa.CheckConstraint("data_mode IN ('DEMO', 'LIVE')", name=op.f('ck_job_runs_data_mode')),
        sa.CheckConstraint("job_type = 'PROVIDER_SYNC'", name=op.f('ck_job_runs_job_type')),
        *checks('job_runs', ('record_count', 'error_count')))
    op.create_index('uq_job_runs_active_scope', 'job_runs', ['project_id', 'data_mode', 'provider_connection_id', 'job_type'], unique=True,
                    postgresql_nulls_not_distinct=True, postgresql_where=sa.text("status IN ('PENDING', 'RUNNING')"))
    op.create_table('job_steps', *common_columns(),
        sa.Column('job_run_id', sa.UUID(), nullable=False),
        sa.Column('step_type', sa.String(32), nullable=False),
        sa.Column('sequence_no', sa.Integer(), nullable=False),
        sa.Column('attempt_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_job_steps')),
        sa.ForeignKeyConstraint(['job_run_id'], ['job_runs.id'], ondelete='CASCADE', name=op.f('fk_job_steps_job_run_id_job_runs')),
        sa.UniqueConstraint('job_run_id', 'step_type', name='uq_job_steps_run_type'),
        sa.UniqueConstraint('job_run_id', 'sequence_no', name='uq_job_steps_run_sequence'),
        sa.CheckConstraint("step_type IN ('PROVIDER_SYNC', 'NORMALIZE_IMPORT', 'TREND_REBUILD', 'AI_INSIGHT_GENERATE')", name=op.f('ck_job_steps_step_type')),
        sa.CheckConstraint('sequence_no > 0', name=op.f('ck_job_steps_sequence_positive')),
        *checks('job_steps', ('attempt_count', 'record_count', 'error_count')))
    for table, owner in (('post_metrics', 'post_id'), ('account_metrics', 'account_id')):
        op.add_column(table, sa.Column('ingest_key', sa.String(255), nullable=True))
        op.add_column(table, sa.Column('ingest_job_run_id', sa.UUID(), nullable=True))
        op.create_foreign_key(op.f(f'fk_{table}_ingest_job_run_id_job_runs'), table, 'job_runs', ['ingest_job_run_id'], ['id'], ondelete='SET NULL')
        op.create_index(f'uq_{table}_ingest_key', table, [owner, 'ingest_key'], unique=True, postgresql_where=sa.text('ingest_key IS NOT NULL'))
    op.add_column('import_histories', sa.Column('job_run_id', sa.UUID(), nullable=True))
    op.create_foreign_key(op.f('fk_import_histories_job_run_id_job_runs'), 'import_histories', 'job_runs', ['job_run_id'], ['id'], ondelete='SET NULL')


def downgrade():
    op.drop_constraint(op.f('fk_import_histories_job_run_id_job_runs'), 'import_histories', type_='foreignkey')
    op.drop_column('import_histories', 'job_run_id')
    for table in ('account_metrics', 'post_metrics'):
        op.drop_index(f'uq_{table}_ingest_key', table_name=table)
        op.drop_constraint(op.f(f'fk_{table}_ingest_job_run_id_job_runs'), table, type_='foreignkey')
        op.drop_column(table, 'ingest_job_run_id')
        op.drop_column(table, 'ingest_key')
    op.drop_table('job_steps')
    op.drop_index('uq_job_runs_active_scope', table_name='job_runs')
    op.drop_table('job_runs')
