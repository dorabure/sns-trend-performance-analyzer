"""Import provenance; provider credentials remain outside the database."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0005_v2_provider_core'
down_revision = '0004_v2_scheduler_ops'
branch_labels = depends_on = None


def upgrade():
    op.add_column('import_histories', sa.Column('data_origin', sa.String(32), nullable=False, server_default='DEMO_CSV'))
    op.add_column('import_histories', sa.Column('provider_connection_id', UUID(as_uuid=True)))
    op.create_check_constraint('data_origin', 'import_histories', "data_origin IN ('DEMO_CSV', 'X_API', 'INSTAGRAM_API')")
    op.create_foreign_key('fk_import_histories_provider_connection_id_provider_connections', 'import_histories', 'provider_connections', ['provider_connection_id'], ['id'], ondelete='SET NULL')
    op.create_index('idx_import_histories_provider_connection_id', 'import_histories', ['provider_connection_id'])
    op.create_index('idx_import_histories_job_run_id', 'import_histories', ['job_run_id'])


def downgrade():
    op.drop_index('idx_import_histories_job_run_id', 'import_histories')
    op.drop_index('idx_import_histories_provider_connection_id', 'import_histories')
    op.drop_constraint('fk_import_histories_provider_connection_id_provider_connections', 'import_histories', type_='foreignkey')
    op.drop_constraint('data_origin', 'import_histories', type_='check')
    op.drop_column('import_histories', 'provider_connection_id')
    op.drop_column('import_histories', 'data_origin')
