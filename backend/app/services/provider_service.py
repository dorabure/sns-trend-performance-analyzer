"""DB-only project context and provider settings. No external calls or sync."""
from app.repositories.provider_repository import ProviderRepository
from app.schemas.provider import ProviderResponse, ProviderSummary, ProviderDetail, SyncStateResponse, ProjectContext
from app.services.settings_service import SettingsService, SettingsFailure
from app.core.live_operations import live_enabled
from app.repositories.job_repository import JobRepository
from datetime import datetime, timezone
from app.providers.core import ProviderRegistry, ProviderError, ProviderCapability, checked_capabilities
from app.providers.secret_store import ProviderCredentialResolver
from app.providers.credential_manager import CredentialManagerRouter


class ProviderService(SettingsService):
    def __init__(self, session_factory, provider_repository=None, *, registry=None, resolver=None, enabled=None):
        super().__init__(session_factory)
        self.providers = provider_repository or ProviderRepository()
        self.registry = registry or ProviderRegistry()
        self.resolver = resolver or CredentialManagerRouter(session_factory)
        self.enabled = enabled or live_enabled

    def context(self, project_id):
        with self.transaction() as session:
            project = self.project(session, project_id)
            rows = self.providers.connections(session, project_id) if project.data_mode == "LIVE" else []
            return ProjectContext(project_id=project.project_id, project_name=project.name,
                                  live_operations_enabled=live_enabled(),
                                  data_mode=project.data_mode, platforms=self.repository.platforms(session, project_id),
                                  providers=[ProviderSummary.model_validate(row) for row in rows])

    def list(self, project_id):
        with self.transaction() as session:
            project = self.project(session, project_id)
            if project.data_mode == "DEMO":
                return []
            return [self.response(session, row) for row in self.providers.connections(session, project_id)]

    def response(self, session, row):
        result = ProviderResponse.model_validate(row)
        if row.provider_type == 'INSTAGRAM_API':
            available = self.available_capabilities(row.provider_type)
            result.capabilities = [cap for cap in result.capabilities if cap in available]
        result.sync_in_progress = JobRepository().active(session, row.project_id, 'LIVE', row.id) is not None
        return result

    def available_capabilities(self, provider_type):
        remote, _ = self.registry.get(provider_type)
        return checked_capabilities(remote.capabilities())

    def connection(self, session, project_id, provider_type, *, lock=False):
        project = self.project(session, project_id)
        if project.data_mode != "LIVE":
            raise SettingsFailure(409, "PROVIDER_REQUIRES_LIVE", "Provider settings require a LIVE project")
        connection = self.providers.connection(session, project_id, provider_type, lock=lock)
        if connection is None:
            raise SettingsFailure(404, "NOT_FOUND", "Provider was not found")
        return connection

    def detail(self, project_id, provider_type):
        with self.transaction() as session:
            connection = self.connection(session, project_id, provider_type)
            return ProviderDetail(**self.response(session, connection).model_dump(),
                                  sync_states=[SyncStateResponse.model_validate(row)
                                               for row in self.providers.states(session, connection.id)])

    def patch(self, project_id, provider_type, request):
        with self.transaction() as session:
            connection = self.connection(session, project_id, provider_type, lock=True)
            connection.enabled = request.enabled
            connection.connection_status = "NOT_CONFIGURED" if request.enabled else "DISABLED"
            session.flush()
            return self.response(session, connection)

    def capabilities(self, project_id, provider_type):
        with self.transaction() as session:
            row = self.connection(session, project_id, provider_type)
            values = (self.available_capabilities(row.provider_type)
                      if row.provider_type == 'INSTAGRAM_API' else checked_capabilities(row.capabilities))
            return {'provider_type': row.provider_type,
                    'capabilities': {cap.value: cap.value in values for cap in ProviderCapability}}

    def validate(self, project_id, provider_type):
        failure = None
        with self.transaction() as session:
            row = self.connection(session, project_id, provider_type, lock=True)
            if not self.enabled():
                raise SettingsFailure(409, 'LIVE_MODE_DISABLED', 'Live operations are disabled')
            now = datetime.now(timezone.utc)
            row.last_attempt_at = now
            try:
                remote, _ = self.registry.get(row.provider_type)
                credential = self.resolver.resolve_connection(row, session) if hasattr(self.resolver, 'resolve_connection') else self.resolver.resolve(row.provider_type, row.credential_ref)
                result = remote.validate_connection(credential)
                if row.remote_account_id is not None and row.remote_account_id != result.remote_account_id:
                    raise ProviderError('PROVIDER_SCOPE_INVALID')
                caps = checked_capabilities(result.capabilities)
                required = {'ACCOUNT_PROFILE', 'OWN_POSTS', 'OWN_METRICS'}
                if row.provider_type == 'INSTAGRAM_API':
                    required = {'ACCOUNT_PROFILE'}
                    available = self.available_capabilities(row.provider_type)
                    caps = [cap for cap in caps if cap in available]
                if not required <= set(caps):
                    raise ProviderError('PROVIDER_CAPABILITY_UNAVAILABLE')
                row.connection_status = 'CONNECTED' if row.enabled else 'DISABLED'
                row.last_success_at, row.remote_account_id, row.capabilities = now, result.remote_account_id, caps
                row.last_error_code = row.last_error_summary = None
                response = dict(provider_type=row.provider_type, valid=True, connection_status=row.connection_status,
                    credential_configured=True, remote_account_id=row.remote_account_id, capabilities=caps, validated_at=now)
            except (ProviderError, ValueError) as error:
                failure = error.code if isinstance(error, ProviderError) else 'PROVIDER_RESPONSE_INVALID'
                row.connection_status = 'ERROR' if row.enabled else 'DISABLED'
                row.last_error_code, row.last_error_summary = failure, 'Provider validation failed'
        if failure:
            raise SettingsFailure(409, failure, 'Provider validation failed')
        return response
