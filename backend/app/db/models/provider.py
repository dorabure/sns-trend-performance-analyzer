import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, event, false, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.core.provider_metadata import credential_reference, safe_metadata
from app.db.base import Base, Timestamps
from app.providers.core import checked_capabilities


class ProviderConnection(Timestamps, Base):
    __tablename__ = "provider_connections"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.project_id", ondelete="CASCADE"))
    provider_type: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=false())
    connection_status: Mapped[str] = mapped_column(String(32), server_default=text("'NOT_CONFIGURED'"))
    credential_ref: Mapped[str | None] = mapped_column(String(128))
    remote_account_id: Mapped[str | None] = mapped_column(String(255))
    capabilities: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_record_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_error_code: Mapped[str | None] = mapped_column(String(128))
    last_error_summary: Mapped[str | None] = mapped_column(String(1000))
    __table_args__ = (
        CheckConstraint("provider_type IN ('X_API', 'INSTAGRAM_API')", name="provider_type"),
        CheckConstraint("connection_status IN ('NOT_CONFIGURED', 'CONNECTED', 'ERROR', 'DISABLED')", name="connection_status"),
        CheckConstraint("last_record_count >= 0", name="last_record_count_nonnegative"),
        UniqueConstraint("project_id", "provider_type", name="uq_provider_connections_project_provider"),
        Index("idx_provider_connections_project_enabled", "project_id", "enabled"),
    )

    @validates("credential_ref")
    def validate_reference(self, key, value):
        return credential_reference(value)

    @validates("capabilities", "last_error_code", "last_error_summary")
    def validate_metadata(self, key, value):
        if key == 'capabilities':
            return checked_capabilities(value)
        return safe_metadata(value)


@event.listens_for(ProviderConnection, "before_insert")
@event.listens_for(ProviderConnection, "before_update")
def validate_connection_before_write(mapper, connection, target):
    credential_reference(target.credential_ref)
    checked_capabilities(target.capabilities or [])
    for value in (target.capabilities, target.last_error_code, target.last_error_summary):
        safe_metadata(value)


class ProviderSyncState(Timestamps, Base):
    __tablename__ = "provider_sync_states"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("provider_connections.id", ondelete="CASCADE"))
    sync_resource_type: Mapped[str] = mapped_column(String(32))
    cursor: Mapped[str | None] = mapped_column(Text)
    last_remote_id: Mapped[str | None] = mapped_column(String(255))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_result: Mapped[str | None] = mapped_column(String(32))
    last_record_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    state_json: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    __table_args__ = (
        CheckConstraint("sync_resource_type IN ('ACCOUNT', 'POSTS', 'METRICS', 'INSIGHTS')", name="sync_resource_type"),
        CheckConstraint("last_record_count >= 0", name="last_record_count_nonnegative"),
        UniqueConstraint("provider_connection_id", "sync_resource_type", name="uq_provider_sync_states_provider_resource"),
    )

    @validates("state_json", "cursor", "last_result")
    def validate_metadata(self, key, value):
        return safe_metadata(value)


@event.listens_for(ProviderSyncState, "before_insert")
@event.listens_for(ProviderSyncState, "before_update")
def validate_state_before_write(mapper, connection, target):
    for value in (target.state_json, target.cursor, target.last_result):
        safe_metadata(value)
