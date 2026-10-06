"""Project data modes and provider DB foundation; preserve Version 1 keys."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_v2_data_mode_and_providers"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def timestamps():
    return [sa.Column(name, sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False)
            for name in ("created_at", "updated_at")]


def upgrade():
    op.add_column("projects", sa.Column("data_mode", sa.String(16), server_default=sa.text("'DEMO'"), nullable=False))
    op.create_check_constraint(op.f("ck_projects_data_mode"), "projects", "data_mode IN ('DEMO', 'LIVE')")
    op.create_table(
        "provider_connections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("provider_type", sa.String(32), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("connection_status", sa.String(32), server_default=sa.text("'NOT_CONFIGURED'"), nullable=False),
        sa.Column("credential_ref", sa.String(128), nullable=True),
        sa.Column("remote_account_id", sa.String(255), nullable=True),
        sa.Column("capabilities", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_record_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error_code", sa.String(128), nullable=True),
        sa.Column("last_error_summary", sa.String(1000), nullable=True),
        *timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_connections")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="CASCADE", name=op.f("fk_provider_connections_project_id_projects")),
        sa.UniqueConstraint("project_id", "provider_type", name="uq_provider_connections_project_provider"),
        sa.CheckConstraint("provider_type IN ('X_API', 'INSTAGRAM_API')", name=op.f("ck_provider_connections_provider_type")),
        sa.CheckConstraint("connection_status IN ('NOT_CONFIGURED', 'CONNECTED', 'ERROR', 'DISABLED')", name=op.f("ck_provider_connections_connection_status")),
        sa.CheckConstraint("last_record_count >= 0", name=op.f("ck_provider_connections_last_record_count_nonnegative")),
    )
    op.create_index("idx_provider_connections_project_enabled", "provider_connections", ["project_id", "enabled"])
    op.create_table(
        "provider_sync_states",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("provider_connection_id", sa.UUID(), nullable=False),
        sa.Column("sync_resource_type", sa.String(32), nullable=False),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column("last_remote_id", sa.String(255), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_result", sa.String(32), nullable=True),
        sa.Column("last_record_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("state_json", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        *timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_sync_states")),
        sa.ForeignKeyConstraint(["provider_connection_id"], ["provider_connections.id"], ondelete="CASCADE", name=op.f("fk_provider_sync_states_provider_connection_id_provider_connections")),
        sa.UniqueConstraint("provider_connection_id", "sync_resource_type", name="uq_provider_sync_states_provider_resource"),
        sa.CheckConstraint("sync_resource_type IN ('ACCOUNT', 'POSTS', 'METRICS', 'INSIGHTS')", name=op.f("ck_provider_sync_states_sync_resource_type")),
        sa.CheckConstraint("last_record_count >= 0", name=op.f("ck_provider_sync_states_last_record_count_nonnegative")),
    )
    for table in ("sns_accounts", "sns_posts"):
        op.add_column(table, sa.Column("data_origin", sa.String(32), server_default=sa.text("'DEMO_CSV'"), nullable=False))
        op.add_column(table, sa.Column("provider_connection_id", sa.UUID(), nullable=True))
        op.create_check_constraint(op.f(f"ck_{table}_data_origin"), table, "data_origin IN ('DEMO_CSV', 'X_API', 'INSTAGRAM_API')")
        op.create_foreign_key(op.f(f"fk_{table}_provider_connection_id_provider_connections"), table, "provider_connections", ["provider_connection_id"], ["id"], ondelete="SET NULL")


def downgrade():
    for table in ("sns_posts", "sns_accounts"):
        op.drop_constraint(op.f(f"fk_{table}_provider_connection_id_provider_connections"), table, type_="foreignkey")
        op.drop_constraint(op.f(f"ck_{table}_data_origin"), table, type_="check")
        op.drop_column(table, "provider_connection_id")
        op.drop_column(table, "data_origin")
    op.drop_table("provider_sync_states")
    op.drop_index("idx_provider_connections_project_enabled", table_name="provider_connections")
    op.drop_table("provider_connections")
    op.drop_constraint(op.f("ck_projects_data_mode"), "projects", type_="check")
    op.drop_column("projects", "data_mode")
