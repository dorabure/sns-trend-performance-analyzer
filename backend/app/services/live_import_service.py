"""Strict live business transaction, reusing CSV repository UPSERTs and matching."""
import hashlib
import json
from datetime import timezone

from sqlalchemy import select
from app.core.provider_metadata import safe_metadata
from app.db.models import (Project, ProjectPlatform, ProviderConnection, SNSAccount, SNSPost,
    JobRun, WatchTerm, WatchTopic, ImportHistory, ProviderSyncState)
from app.providers.core import ProviderError
from app.repositories.import_repository import ImportRepository
from app.services.matching_service import TermCandidate

PLATFORMS = {'X_API': 'X', 'INSTAGRAM_API': 'INSTAGRAM'}


def ingest_key(provider_id, remote_id, observed_at, resource):
    identity = observed_at.astimezone(timezone.utc).isoformat() if hasattr(observed_at, 'astimezone') else observed_at.isoformat()
    return hashlib.sha256(json.dumps([1, str(provider_id), remote_id, identity, resource], ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


class LiveImportService:
    def __init__(self, factory, repository=None):
        self.factory, self.repository = factory, repository or ImportRepository()

    def import_data(self, job_id, profile, account_metric, posts, observed_at):
        try:
            if observed_at.utcoffset() is None:
                raise ProviderError('PROVIDER_SCOPE_INVALID')
            with self.factory() as session, session.begin():
                job = session.scalar(select(JobRun).where(JobRun.id == job_id).with_for_update())
                if not job or job.status != 'RUNNING' or job.data_mode != 'LIVE':
                    raise ProviderError('PROVIDER_SCOPE_INVALID')
                project = session.scalar(select(Project).where(Project.project_id == job.project_id).with_for_update())
                provider = session.scalar(select(ProviderConnection).where(ProviderConnection.id == job.provider_connection_id).with_for_update())
                if not project or not project.is_active or project.data_mode != 'LIVE' or not provider or not provider.enabled or provider.project_id != project.project_id:
                    raise ProviderError('PROVIDER_SCOPE_INVALID')
                platform = PLATFORMS.get(provider.provider_type)
                enabled_platforms = set(session.scalars(select(ProjectPlatform.platform).where(ProjectPlatform.project_id == project.project_id)))
                if platform not in enabled_platforms or profile.platform != platform or account_metric.platform != platform or account_metric.account_name != profile.username:
                    raise ProviderError('PROVIDER_SCOPE_INVALID')
                if not profile.remote_account_id or not profile.username:
                    raise ProviderError('PROVIDER_RESPONSE_INVALID')
                if provider.remote_account_id and provider.remote_account_id != profile.remote_account_id:
                    raise ProviderError('PROVIDER_SCOPE_INVALID')
                account = session.scalar(select(SNSAccount).where(SNSAccount.project_id == project.project_id,
                    SNSAccount.platform == platform, SNSAccount.account_role == 'OWN', SNSAccount.is_active.is_(True)))
                if account and (account.provider_connection_id != provider.id or account.data_origin != provider.provider_type or account.platform_account_id != profile.remote_account_id):
                    raise ProviderError('PROVIDER_SCOPE_INVALID')
                if account is None:
                    account = SNSAccount(project_id=project.project_id, platform=platform, account_role='OWN',
                        account_name=profile.username, data_origin=provider.provider_type, provider_connection_id=provider.id,
                        platform_account_id=profile.remote_account_id)
                    session.add(account)
                account.account_name, account.display_name, account.profile_url = profile.username, profile.display_name, profile.profile_url
                session.flush()
                safe_metadata(account_metric.raw_metrics)
                self.repository.save_account_metric(session, account.account_id, account_metric,
                    ingest_key=ingest_key(provider.id, profile.remote_account_id, account_metric.recorded_date, 'ACCOUNT_DAILY'), ingest_job_run_id=job_id)
                terms = session.scalars(select(WatchTerm).join(WatchTopic).where(WatchTopic.project_id == project.project_id,
                    WatchTopic.is_active.is_(True), WatchTerm.is_active.is_(True))).all()
                candidates = [TermCandidate(t.term_id, t.topic_id, t.term, t.normalized_term, t.term_type) for t in terms]
                for post in posts:
                    if post.platform != platform or post.source_type != 'OWN' or post.account_name != profile.username or not post.platform_post_id or post.posted_at.utcoffset() is None:
                        raise ProviderError('PROVIDER_SCOPE_INVALID')
                    safe_metadata(post.raw_data)
                    existing = session.scalar(select(SNSPost).where(SNSPost.project_id == project.project_id,
                        SNSPost.platform == platform, SNSPost.platform_post_id == post.platform_post_id))
                    if existing and (existing.provider_connection_id != provider.id or existing.account_id != account.account_id or existing.data_origin != provider.provider_type or existing.source_type != 'OWN'):
                        raise ProviderError('PROVIDER_SCOPE_INVALID')
                    self.repository.save_post(session, project.project_id, account.account_id, post, observed_at, candidates,
                        data_origin=provider.provider_type, provider_connection_id=provider.id,
                        ingest_key=ingest_key(provider.id, post.platform_post_id, observed_at, 'POST_METRIC'), ingest_job_run_id=job_id)
                # One audit record per job/dataset; stable business snapshots survive a new job.
                for kind, count in [('OWN_POSTS', len(posts)), ('ACCOUNT_DAILY', 1)]:
                    history = session.scalar(select(ImportHistory).where(ImportHistory.job_run_id == job_id, ImportHistory.import_type == kind))
                    if history is None:
                        session.add(ImportHistory(project_id=project.project_id, job_run_id=job_id, import_type=kind,
                            data_origin=provider.provider_type, provider_connection_id=provider.id, filename='provider_sync',
                            status='SUCCESS', total_count=count, success_count=count, error_count=0))
            return len(posts) + 1
        except ProviderError:
            raise
        except Exception:
            raise ProviderError('PROVIDER_IMPORT_FAILED') from None


class ProviderSyncStateService:
    def __init__(self, factory):
        self.factory = factory

    def checkpoint(self, job_id, account, page, observed_at):
        try:
            safe_metadata([page.next_cursor, page.last_remote_id, account.remote_account_id])
            with self.factory() as session, session.begin():
                job = session.scalar(select(JobRun).where(JobRun.id == job_id).with_for_update())
                if job is None or job.status != 'RUNNING':
                    raise ProviderError('PROVIDER_SCOPE_INVALID')
                for resource, count in [('ACCOUNT', 1), ('POSTS', len(page.records)), ('METRICS', len(page.records) + 1)]:
                    state = session.scalar(select(ProviderSyncState).where(ProviderSyncState.provider_connection_id == job.provider_connection_id,
                        ProviderSyncState.sync_resource_type == resource).with_for_update())
                    if state is None:
                        state = ProviderSyncState(provider_connection_id=job.provider_connection_id, sync_resource_type=resource)
                        session.add(state)
                    state.cursor = page.next_cursor if resource == 'POSTS' else None
                    state.last_remote_id = page.last_remote_id if resource == 'POSTS' else account.remote_account_id
                    state.last_synced_at = state.last_success_at = observed_at
                    state.last_result, state.last_record_count = 'SUCCESS', count
        except ProviderError:
            raise
        except Exception:
            raise ProviderError('PROVIDER_CHECKPOINT_FAILED') from None
