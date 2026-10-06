from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from app.schemas.settings import Contract, DataMode
from app.dto.normalized import Platform
from app.providers.core import ProviderCapability


class ProviderType(StrEnum):
    X_API = "X_API"
    INSTAGRAM_API = "INSTAGRAM_API"


class ConnectionStatus(StrEnum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    CONNECTED = "CONNECTED"
    ERROR = "ERROR"
    DISABLED = "DISABLED"


class SyncResourceType(StrEnum):
    ACCOUNT = "ACCOUNT"
    POSTS = "POSTS"
    METRICS = "METRICS"
    INSIGHTS = "INSIGHTS"


class ProviderPatch(Contract):
    enabled: bool = Field(strict=True)


class ProviderSummary(Contract):
    provider_type: ProviderType
    enabled: bool
    connection_status: ConnectionStatus


class ProviderResponse(ProviderSummary):
    sync_in_progress: bool = False
    id: UUID
    remote_account_id: str | None
    capabilities: list[str]
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    last_record_count: int


class SyncStateResponse(Contract):
    sync_resource_type: SyncResourceType
    last_synced_at: datetime | None
    last_success_at: datetime | None
    last_result: str | None
    last_record_count: int


class ProviderDetail(ProviderResponse):
    sync_states: list[SyncStateResponse]


class ProviderValidationResponse(Contract):
    provider_type: ProviderType
    valid: bool
    connection_status: ConnectionStatus
    credential_configured: bool
    remote_account_id: str | None
    capabilities: list[ProviderCapability]
    validated_at: datetime


class ProviderCapabilitiesResponse(Contract):
    provider_type: ProviderType
    capabilities: dict[ProviderCapability, bool]


class ProjectContext(Contract):
    live_operations_enabled: bool = False
    project_id: UUID
    project_name: str
    data_mode: DataMode
    platforms: list[Platform]
    providers: list[ProviderSummary]
