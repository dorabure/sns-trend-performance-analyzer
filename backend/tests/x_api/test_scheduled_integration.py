"""Real schedule/worker/credential/import code with exclusively mocked HTTP."""
import json
from datetime import timedelta
import httpx
import pytest
from sqlalchemy import select, func
from app.db.models import ProviderConnection, ProviderSyncState, JobRun, JobStep, SNSPost, PostMetric, ImportHistory
from app.providers.core import ProviderRegistry, ProviderError
from app.providers.credential_manager import CredentialManagerRouter
from app.providers.http_client import ProviderHTTPClient
from app.providers.x_api_provider import XApiProvider, XProviderNormalizer
from app.providers.x_oauth import XCredentialManager, XTokenClient
from app.services.job_operations_service import JobOperationsService
from app.services.job_dispatch_service import JobDispatchService
from app.services.provider_sync_handler import ProviderSyncHandler
from app.schemas.job_operations import ScheduleCreate
from app.jobs.tasks import execute_job
from tests.x_api.test_provider import OBS, USER, post


def setup(c, monkeypatch, *, refresh=False, failure=None, empty=False):
    with c.factory() as s, s.begin():
        provider = s.get(ProviderConnection, c.provider)
        provider.connection_status = 'CONNECTED'
        provider.capabilities = ['ACCOUNT_PROFILE', 'OWN_POSTS', 'OWN_METRICS']
        s.add(ProviderSyncState(provider_connection_id=c.provider, sync_resource_type='POSTS', cursor=None, last_remote_id='99'))
    c.store.set_secret(c.ref, json.dumps(dict(schema_version=1, access_token='test-only-old',
        refresh_token='test-only-refresh', expires_at=(OBS if refresh else OBS+timedelta(days=1)).isoformat())))
    old = c.store.path(c.ref).read_bytes()
    calls = []
    def http(request):
        calls.append(request)
        if request.method == 'POST':
            if failure == 'refresh': return httpx.Response(400, json={'error': 'invalid_grant'})
            return httpx.Response(200, json=dict(token_type='bearer', access_token='test-only-new',
                refresh_token='test-only-new-refresh', expires_in=7200))
        assert request.headers['Authorization'] == ('Bearer test-only-new' if refresh else 'Bearer test-only-old')
        return httpx.Response(200, json=USER if request.url.path == '/2/users/me' else
            {'meta': {'result_count': 0}} if empty else {'data': [post('100')]})
    client = ProviderHTTPClient(transport=httpx.MockTransport(http), sleep=lambda _: None)
    remote = XApiProvider(client, enabled=lambda: True)
    registry = ProviderRegistry({'X_API': lambda: (remote, XProviderNormalizer())})
    manager = XCredentialManager(c.factory, c.resolver, XTokenClient(c.source, client), enabled=lambda: True, now=lambda: OBS)
    router = CredentialManagerRouter(c.factory, x_manager=manager)
    handler = ProviderSyncHandler(c.factory, registry=registry, resolver=router, enabled=lambda: True)
    if failure == 'import':
        class FailedImport:
            def import_data(self, *args): raise ProviderError('PROVIDER_IMPORT_FAILED')
        handler.importer = FailedImport()
    monkeypatch.setenv('LIVE_MODE_ENABLED', 'true')
    monkeypatch.setattr('app.db.session.SessionLocal', c.factory)
    monkeypatch.setattr('app.services.provider_sync_handler.ProviderSyncHandler', lambda _: handler)
    delivered = []
    dispatcher = JobDispatchService(c.factory, enabled=lambda: True, publisher=delivered.append)
    ops = JobOperationsService(c.factory, enabled=lambda: True, dispatcher=dispatcher, clock=lambda: OBS, registry=registry)
    row = ops.create_schedule(c.project, ScheduleCreate(provider_connection_id=c.provider,
        schedule_mode='INTERVAL', interval_seconds=60, enabled=True))
    return ops, dispatcher, delivered, calls, row, old


@pytest.mark.parametrize('refresh,empty', [(False, False), (True, False), (False, True)])
def test_scheduled_production_worker_router_import_checkpoint_redelivery(x_context, monkeypatch, refresh, empty):
    c = x_context
    ops, dispatcher, delivered, calls, row, _ = setup(c, monkeypatch, refresh=refresh, empty=empty)
    # Recreate the service while retaining PostgreSQL schedules and encrypted credentials.
    ops = JobOperationsService(c.factory, enabled=lambda: True, dispatcher=dispatcher, registry=ops.registry)
    assert ops.tick(OBS+timedelta(seconds=125)) == 1
    jid = delivered[0]
    accepted = ops.get_schedule(c.project, row['id'])
    assert accepted['last_job_run_id'] == jid and accepted['last_run_at'] == OBS+timedelta(seconds=125)
    assert accepted['next_run_at'] == OBS+timedelta(seconds=180)
    assert ops.set_enabled(c.project, row['id'], False)['next_run_at'] is None
    assert execute_job.run(str(jid)) == 'SUCCESS'
    assert [r.method for r in calls] == (['POST', 'GET', 'GET'] if refresh else ['GET', 'GET'])
    assert str(calls[-1].url.params['since_id']) == '99'
    detail = ops.get_job(c.project, jid)
    assert detail['trigger_type'] == 'SCHEDULED' and detail['job_schedule_id'] == row['id']
    assert detail['scheduled_for'] == OBS+timedelta(seconds=60)
    assert [s['status'] for s in detail['steps']] == ['SUCCESS', 'SUCCESS', 'SKIPPED', 'SKIPPED']
    with c.factory() as s:
        histories = list(s.scalars(select(ImportHistory).where(ImportHistory.job_run_id == jid)))
        assert len(histories) == 2 and {h.import_type for h in histories} == {'OWN_POSTS', 'ACCOUNT_DAILY'}
        assert all(h.data_origin == 'X_API' and h.provider_connection_id == c.provider for h in histories)
        states = list(s.scalars(select(ProviderSyncState).where(ProviderSyncState.provider_connection_id == c.provider)))
        assert {state.sync_resource_type for state in states} == {'ACCOUNT', 'POSTS', 'METRICS'}
        assert all(state.last_result == 'SUCCESS' and state.last_success_at == detail['scheduled_for'] for state in states)
        posts = next(state for state in states if state.sync_resource_type == 'POSTS')
        assert posts.last_remote_id == ('99' if empty else '100')
        assert posts.last_record_count == (0 if empty else 1)
        metric = s.scalar(select(PostMetric).where(PostMetric.ingest_job_run_id == jid))
        if not empty: assert metric.recorded_at == detail['scheduled_for'] and metric.ingest_key
        counts = [s.scalar(select(func.count()).select_from(model).where(column == jid))
            for model, column in ((PostMetric, PostMetric.ingest_job_run_id), (ImportHistory, ImportHistory.job_run_id), (JobStep, JobStep.job_run_id))]
    call_count = len(calls)
    assert execute_job.run(str(jid)) == 'NO_OP' and len(calls) == call_count
    with c.factory() as s:
        assert counts == [s.scalar(select(func.count()).select_from(model).where(column == jid))
            for model, column in ((PostMetric, PostMetric.ingest_job_run_id), (ImportHistory, ImportHistory.job_run_id), (JobStep, JobStep.job_run_id))]
    assert ops.tick(OBS+timedelta(days=1)) == 0 and len(delivered) == 1


@pytest.mark.parametrize('failure', ['refresh', 'import'])
def test_scheduled_failure_preserves_checkpoint_and_credential(x_context, monkeypatch, failure):
    c = x_context
    ops, _, delivered, calls, row, old = setup(c, monkeypatch, refresh=failure == 'refresh', failure=failure)
    assert ops.tick(OBS+timedelta(seconds=61)) == 1
    assert execute_job.run(str(delivered[0])) == 'FAILED'
    assert c.store.path(c.ref).read_bytes() == old
    with c.factory() as s:
        state = s.scalar(select(ProviderSyncState).where(ProviderSyncState.provider_connection_id == c.provider))
        assert state.last_remote_id == '99' and state.cursor is None and state.last_success_at is None
        assert s.get(ProviderConnection, c.provider).connection_status == 'ERROR'
        assert s.scalar(select(func.count()).select_from(SNSPost).where(SNSPost.project_id == c.project)) == 0
    assert ops.get_job(c.project, delivered[0])['error_code'] == ('PROVIDER_AUTH_FAILED' if failure == 'refresh' else 'PROVIDER_IMPORT_FAILED')
    if failure == 'refresh': assert len(calls) == 1 and calls[0].method == 'POST'
    assert ops.get_schedule(c.project, row['id'])['enabled']
    ops.set_enabled(c.project, row['id'], False)


def test_scheduled_broker_recovery_same_id_single_terminal_result(x_context, monkeypatch):
    c = x_context
    ops, dispatcher, delivered, calls, row, _ = setup(c, monkeypatch)
    def unavailable(_): raise RuntimeError('test-only-broker-unavailable')
    dispatcher.publisher = unavailable
    assert ops.tick(OBS+timedelta(seconds=61)) == 1 and not delivered
    jid = ops.get_schedule(c.project, row['id'])['last_job_run_id']
    assert ops.get_job(c.project, jid)['enqueued_at'] is None
    ops.set_enabled(c.project, row['id'], False)
    dispatcher.publisher = delivered.append
    assert dispatcher.reconcile(now=OBS+timedelta(seconds=62)) == 1
    assert delivered == [jid] and execute_job.run(str(jid)) == 'SUCCESS'
    assert execute_job.run(str(jid)) == 'NO_OP' and len(calls) == 2
    assert dispatcher.reconcile(now=OBS+timedelta(days=1)) == 0


def test_scheduled_stale_running_recovery_does_not_refetch(x_context, monkeypatch):
    c = x_context
    ops, _, delivered, calls, row, _ = setup(c, monkeypatch)
    assert ops.tick(OBS+timedelta(seconds=61)) == 1
    jid = delivered[0]
    assert c.jobs.claim(jid)
    c.jobs.transition_step(jid, 'PROVIDER_SYNC', 'RUNNING')
    c.jobs.heartbeat(jid, OBS)
    ops.set_enabled(c.project, row['id'], False)
    assert c.jobs.recover_stale(now=OBS+timedelta(seconds=901)) == 1
    assert execute_job.run(str(jid)) == 'NO_OP' and not calls
    assert ops.get_job(c.project, jid)['error_code'] == 'WORKER_HEARTBEAT_TIMEOUT'
