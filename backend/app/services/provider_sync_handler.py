"""Provider-independent pipeline. Test providers must be explicitly injected."""
from datetime import datetime, timezone
from sqlalchemy import select
from app.core.live_operations import live_enabled
from app.db.models import JobRun, ProviderConnection, ProviderSyncState, Project
from app.providers.core import ProviderRegistry, ProviderContext, ProviderError, ProviderCapability, checked_capabilities
from app.providers.secret_store import ProviderCredentialResolver
from app.providers.credential_manager import CredentialManagerRouter
from app.services.live_import_service import LiveImportService, ProviderSyncStateService


class ProviderSyncHandler:
    def __init__(self, factory, *, registry=None, resolver=None, importer=None, states=None, enabled=None, trend=None):
        self.factory = factory
        self.registry, self.resolver = registry or ProviderRegistry(), resolver or CredentialManagerRouter(factory)
        self.importer, self.states = importer or LiveImportService(factory), states or ProviderSyncStateService(factory)
        self.enabled, self.trend = enabled or live_enabled, trend

    def __call__(self, job_id, jobs):
        provider_id = None
        try:
            if not self.enabled():
                raise ProviderError('LIVE_MODE_DISABLED')
            jobs.heartbeat(job_id)
            jobs.transition_step(job_id, 'PROVIDER_SYNC', 'RUNNING')
            with self.factory() as session:
                job = session.get(JobRun, job_id)
                provider = session.get(ProviderConnection, job.provider_connection_id)
                project = session.get(Project, job.project_id)
                if not project or not project.is_active or project.data_mode != 'LIVE' or not provider or provider.project_id != job.project_id:
                    raise ProviderError('PROVIDER_SCOPE_INVALID')
                provider_id = provider.id
                if not provider.enabled:
                    raise ProviderError('PROVIDER_NOT_READY')
                remote, normalizer = self.registry.get(provider.provider_type)
                if hasattr(remote, 'ensure_sync_ready'):
                    remote.ensure_sync_ready()
                credential = self.resolver.resolve_connection(provider) if hasattr(self.resolver, 'resolve_connection') else self.resolver.resolve(provider.provider_type, provider.credential_ref)
                caps = checked_capabilities(remote.capabilities())
                if not {'ACCOUNT_PROFILE', 'OWN_POSTS', 'OWN_METRICS'} <= set(caps):
                    raise ProviderError('PROVIDER_CAPABILITY_UNAVAILABLE')
                observation = job.scheduled_for or job.created_at
                states = list(session.scalars(select(ProviderSyncState).where(ProviderSyncState.provider_connection_id == provider.id)))
                cursors = {s.sync_resource_type: s.cursor for s in states}
                context = ProviderContext(job.project_id, provider.id, credential, observation, cursors, lambda: jobs.heartbeat(job_id),
                    {s.sync_resource_type: s.last_remote_id for s in states})
            jobs.heartbeat(job_id)
            account = remote.fetch_account(context)
            jobs.heartbeat(job_id)
            page = remote.fetch_posts(context, account)
            jobs.heartbeat(job_id)
            if any(p.remote_account_id != account.remote_account_id for p in page.records):
                raise ProviderError('PROVIDER_SCOPE_INVALID')
            observed = account.observed_at or account.metrics.observed_at or observation
            if observed.utcoffset() is None:
                raise ProviderError('PROVIDER_RESPONSE_INVALID')
            jobs.transition_step(job_id, 'PROVIDER_SYNC', 'SUCCESS', result_summary=getattr(remote, 'rate_metadata', {}))
            jobs.transition_step(job_id, 'NORMALIZE_IMPORT', 'RUNNING')
            jobs.heartbeat(job_id)
            profile, metric = normalizer.normalize_account(account, observed)
            posts = normalizer.normalize_posts(page.records, account)
            jobs.heartbeat(job_id)
            count = self.importer.import_data(job_id, profile, metric, posts, observed)
            jobs.heartbeat(job_id)
            self.states.checkpoint(job_id, account, page, observed)
            jobs.transition_step(job_id, 'NORMALIZE_IMPORT', 'SUCCESS', record_count=count)
            self.connection_result(provider_id, remote_id=account.remote_account_id, capabilities=caps, count=count)
            jobs.heartbeat(job_id)
            if self.trend and ({'MARKET_POSTS', 'TREND_DATA'} & set(caps)):
                jobs.transition_step(job_id, 'TREND_REBUILD', 'RUNNING')
                try:
                    self.trend(context.project_id)
                    jobs.transition_step(job_id, 'TREND_REBUILD', 'SUCCESS')
                except Exception:
                    jobs.transition_step(job_id, 'TREND_REBUILD', 'FAILED', error_count=1, error_code='TREND_REBUILD_FAILED', error_summary='Trend rebuild failed')
            else:
                jobs.transition_step(job_id, 'TREND_REBUILD', 'SKIPPED', result_summary={'reason': 'capability_unavailable'})
            jobs.heartbeat(job_id)
            jobs.transition_step(job_id, 'AI_INSIGHT_GENERATE', 'SKIPPED', result_summary={'reason': 'phase_not_enabled'})
        except ProviderError as error:
            if provider_id:
                self.connection_result(provider_id, code=error.code)
            jobs.fail_execution(job_id, error.code)
        except Exception:
            if provider_id:
                self.connection_result(provider_id, code='PROVIDER_RESPONSE_INVALID')
            jobs.fail_execution(job_id, 'PROVIDER_RESPONSE_INVALID')

    def connection_result(self, provider_id, *, code=None, remote_id=None, capabilities=None, count=0):
        with self.factory() as session, session.begin():
            provider = session.scalar(select(ProviderConnection).where(ProviderConnection.id == provider_id).with_for_update())
            if provider is None:
                return
            provider.last_attempt_at = datetime.now(timezone.utc)
            provider.connection_status = 'DISABLED' if not provider.enabled else 'ERROR' if code else 'CONNECTED'
            provider.last_error_code = code
            provider.last_error_summary = 'Provider operation failed' if code else None
            if code is None:
                provider.last_success_at = provider.last_attempt_at
                provider.remote_account_id, provider.capabilities, provider.last_record_count = remote_id, capabilities or [], count
