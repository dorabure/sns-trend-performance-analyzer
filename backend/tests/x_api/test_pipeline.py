import json
from datetime import timedelta
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.main import app
from app.db.models import SNSAccount, SNSPost, PostMetric, AccountMetric, ImportHistory, ProviderSyncState, ProviderConnection, JobRun, JobStep
from app.providers.core import ProviderRegistry
from app.providers.http_client import ProviderHTTPClient
from app.providers.x_api_provider import XApiProvider, XProviderNormalizer
from app.providers.x_oauth import XCredentialManager
from app.services.provider_sync_handler import ProviderSyncHandler
from app.services.provider_service import ProviderService
from app.services.my_account_service import MyAccountService
from app.services.settings_service import SettingsFailure
from app.api.v1.providers import get_provider_service
from app.api.v1.my_account import get_my_account_service
from app.jobs.runner import JobRunner
from tests.x_api.test_provider import USER, OBS, post


def pipeline(c, responses):
    calls = []
    def mock(request):
        calls.append(request)
        value = responses.pop(0)
        return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value,
            headers={'x-rate-limit-remaining': '74', 'x-rate-limit-reset': '2000000000', 'Authorization': 'private'})
    remote = XApiProvider(ProviderHTTPClient(transport=httpx.MockTransport(mock), sleep=lambda _: None), enabled=lambda: True)
    registry = ProviderRegistry({'X_API': lambda: (remote, XProviderNormalizer())})
    manager = XCredentialManager(c.factory, c.resolver, enabled=lambda: True)
    handler = ProviderSyncHandler(c.factory, registry=registry, resolver=manager, enabled=lambda: True)
    return handler, registry, manager, calls


def run(c, handler, observation=OBS):
    jid = c.jobs.create(c.project, 'LIVE', c.provider, scheduled_for=observation)
    return jid, JobRunner(c.jobs, handler).execute(jid)


def post_count(c):
    with c.factory() as s:
        return s.scalar(select(func.count()).select_from(SNSPost).where(SNSPost.project_id == c.project))


def test_production_provider_validate_import_analytics_incremental_and_metadata(x_context):
    c = x_context
    responses = [USER, USER, {'data': [post('101'), post('100')], 'meta': {'next_token': 'do-not-backfill'}},
        USER, {'data': [post('102')]}]
    handler, registry, manager, calls = pipeline(c, responses)
    service = ProviderService(c.factory, registry=registry, resolver=manager, enabled=lambda: True)
    app.dependency_overrides[get_provider_service] = lambda: service
    app.dependency_overrides[get_my_account_service] = lambda: MyAccountService(c.factory)
    try:
        with TestClient(app) as client:
            base = f'/api/v1/projects/{c.project}'
            response = client.post(base + '/providers/X_API/validate')
            assert response.status_code == 200 and response.json()['remote_account_id'] == '12345'
            assert len(calls) == 1
            assert client.get(base + '/providers/X_API/capabilities').json()['capabilities'] == {
                'ACCOUNT_PROFILE': True, 'OWN_POSTS': True, 'OWN_METRICS': True,
                'MARKET_POSTS': False, 'COMPETITOR_POSTS': False, 'TREND_DATA': False}
            jid, status = run(c, handler)
            assert status == 'SUCCESS' and post_count(c) == 2
            assert JobRunner(c.jobs, handler).execute(jid) == 'NO_OP' and len(calls) == 3
            criteria = {'from': '2026-10-01', 'to': '2026-10-04', 'platform': 'X'}
            own = client.get(base + '/accounts/own/posts', params=criteria)
            assert own.status_code == 200 and own.json()['total'] == 2
            analytics = client.get(base + '/accounts/own/analytics', params=criteria)
            assert analytics.status_code == 200
            jid2, status = run(c, handler, OBS + timedelta(hours=1))
            assert status == 'SUCCESS' and post_count(c) == 3
    finally:
        app.dependency_overrides.pop(get_provider_service, None)
        app.dependency_overrides.pop(get_my_account_service, None)
    assert dict(calls[-1].url.params)['since_id'] == '101'
    with c.factory() as s:
        account = s.scalar(select(SNSAccount).where(SNSAccount.project_id == c.project))
        posts = list(s.scalars(select(SNSPost).where(SNSPost.project_id == c.project)))
        assert account.data_origin == 'X_API' and account.provider_connection_id == c.provider
        assert all(p.data_origin == 'X_API' and p.source_type == 'OWN' and p.account_id == account.account_id for p in posts)
        pm = list(s.scalars(select(PostMetric).join(SNSPost).where(SNSPost.project_id == c.project)))
        assert len(pm) == 3 and all(p.ingest_key and p.ingest_job_run_id in (jid, jid2) for p in pm)
        assert all(p.reach is None and p.views is None and p.shares == 4 for p in pm)
        am = list(s.scalars(select(AccountMetric).where(AccountMetric.account_id == account.account_id)))
        assert len(am) == 1 and am[0].followers == 0
        history = list(s.scalars(select(ImportHistory).where(ImportHistory.project_id == c.project)))
        assert len(history) == 4 and all(h.data_origin == 'X_API' and h.provider_connection_id == c.provider for h in history)
        steps = list(s.scalars(select(JobStep).where(JobStep.job_run_id == jid).order_by(JobStep.sequence_no)))
        assert [s.status for s in steps] == ['SUCCESS', 'SUCCESS', 'SKIPPED', 'SKIPPED']
        assert steps[0].result_summary == {'rate_limit_remaining': 74, 'rate_limit_reset': 2000000000}
        state = s.scalar(select(ProviderSyncState).where(ProviderSyncState.provider_connection_id == c.provider, ProviderSyncState.sync_resource_type == 'POSTS'))
        assert state.last_remote_id == '102' and state.cursor is None
        serialized = json.dumps([st.result_summary for st in steps])
        assert 'private' not in serialized and 'Authorization' not in serialized


@pytest.mark.parametrize('failure,expected', [('page2', 'PROVIDER_AUTH_FAILED'), ('cap', 'PROVIDER_SYNC_LIMIT_EXCEEDED'),
    ('partial', 'PROVIDER_RESPONSE_INVALID')])
def test_pagination_failure_keeps_business_and_checkpoint(x_context, monkeypatch, failure, expected):
    c = x_context
    with c.factory() as s, s.begin():
        s.add(ProviderSyncState(provider_connection_id=c.provider, sync_resource_type='POSTS', last_remote_id='99'))
    if failure == 'cap':
        monkeypatch.setenv('X_INCREMENTAL_MAX_PAGES', '1')
    responses = [USER, {'data': [post('102')], 'meta': {'next_token': 'p2'}}]
    if failure == 'partial': responses[1]['errors'] = [{'detail': 'private'}]
    if failure == 'page2': responses.append(httpx.Response(401))
    handler, _, _, _ = pipeline(c, responses)
    jid, status = run(c, handler)
    assert status == 'FAILED' and post_count(c) == 0
    with c.factory() as s:
        assert s.get(JobRun, jid).error_code == expected
        state = s.scalar(select(ProviderSyncState).where(ProviderSyncState.provider_connection_id == c.provider))
        assert state.last_remote_id == '99' and state.last_success_at is None
        assert s.scalar(select(func.count()).select_from(SNSAccount).where(SNSAccount.project_id == c.project)) == 0


def test_no_data_keeps_last_id(x_context):
    c = x_context
    with c.factory() as s, s.begin():
        s.add(ProviderSyncState(provider_connection_id=c.provider, sync_resource_type='POSTS', last_remote_id='99'))
    handler, _, _, _ = pipeline(c, [USER, {'meta': {'result_count': 0}}])
    _, status = run(c, handler)
    assert status == 'SUCCESS' and post_count(c) == 0
    with c.factory() as s:
        state = s.scalar(select(ProviderSyncState).where(ProviderSyncState.provider_connection_id == c.provider, ProviderSyncState.sync_resource_type == 'POSTS'))
        assert state.last_remote_id == '99' and state.cursor is None


def test_validate_rejects_account_switch_and_preserves_remote_id(x_context):
    c = x_context
    with c.factory() as s, s.begin(): s.get(ProviderConnection, c.provider).remote_account_id = '999'
    _, registry, manager, calls = pipeline(c, [USER])
    service = ProviderService(c.factory, registry=registry, resolver=manager, enabled=lambda: True)
    with pytest.raises(SettingsFailure) as exc: service.validate(c.project, 'X_API')
    assert exc.value.code == 'PROVIDER_SCOPE_INVALID' and len(calls) == 1
    with c.factory() as s:
        row = s.get(ProviderConnection, c.provider)
        assert row.remote_account_id == '999' and row.connection_status == 'ERROR'


def test_same_snapshot_retry_and_new_observation_metrics(x_context):
    c = x_context
    handler, _, _, _ = pipeline(c, [USER, {'data': [post('100')]}, USER, {'data': [post('100')]},
        USER, {'data': [post('100', public_metrics={'like_count': 20})]}])
    # Emulate a business commit followed by checkpoint failure, then same snapshot replay.
    from app.providers.core import ProviderError
    from app.services.live_import_service import ProviderSyncStateService
    class FailedCheckpoint:
        def checkpoint(self, *args): raise ProviderError('PROVIDER_CHECKPOINT_FAILED')
    handler.states = FailedCheckpoint()
    _, status = run(c, handler); assert status == 'FAILED' and post_count(c) == 1
    handler.states = ProviderSyncStateService(c.factory)
    _, status = run(c, handler); assert status == 'SUCCESS'
    # Explicit same-post metric snapshot bypasses incremental fetch by removing checkpoint.
    with c.factory() as s, s.begin():
        state = s.scalar(select(ProviderSyncState).where(ProviderSyncState.provider_connection_id == c.provider, ProviderSyncState.sync_resource_type == 'POSTS'))
        state.last_remote_id = None
    _, status = run(c, handler, OBS + timedelta(days=1)); assert status == 'SUCCESS'
    with c.factory() as s:
        assert s.scalar(select(func.count()).select_from(PostMetric).join(SNSPost).where(SNSPost.project_id == c.project)) == 2
        assert s.scalar(select(func.count()).select_from(AccountMetric).join(SNSAccount).where(SNSAccount.project_id == c.project)) == 2
        assert post_count(c) == 1


def test_manual_202_uuid_dispatch_existing_worker_handler(x_context, monkeypatch):
    from uuid import UUID
    from app.api.v1.job_operations import get_operations_service
    from app.services.job_operations_service import JobOperationsService
    from app.services.job_dispatch_service import JobDispatchService
    from app.jobs.tasks import execute_job
    c = x_context
    handler, _, _, calls = pipeline(c, [USER, {'data': [post('100')]}])
    with c.factory() as s, s.begin():
        row = s.get(ProviderConnection, c.provider)
        row.connection_status = 'CONNECTED'
        row.capabilities = ['ACCOUNT_PROFILE', 'OWN_POSTS', 'OWN_METRICS']
    delivered = []
    dispatcher = JobDispatchService(c.factory, publisher=delivered.append, enabled=lambda: True)
    ops = JobOperationsService(c.factory, dispatcher=dispatcher, enabled=lambda: True)
    app.dependency_overrides[get_operations_service] = lambda: ops
    monkeypatch.setenv('LIVE_MODE_ENABLED', 'true')
    monkeypatch.setattr('app.db.session.SessionLocal', c.factory)
    monkeypatch.setattr('app.services.provider_sync_handler.ProviderSyncHandler', lambda factory: handler)
    try:
        with TestClient(app) as client:
            response = client.post(f'/api/v1/projects/{c.project}/providers/X_API/sync')
            assert response.status_code == 202 and response.json()['status'] == 'PENDING'
            jid = UUID(response.json()['job_run_id'])
            assert delivered == [jid]
            assert execute_job.run(str(jid)) == 'SUCCESS'
            assert execute_job.run(str(jid)) == 'NO_OP' and len(calls) == 2
    finally: app.dependency_overrides.pop(get_operations_service, None)


def test_scheduled_handler_refresh_before_read(x_context, monkeypatch):
    monkeypatch.setenv('X_OAUTH_CLIENT_TYPE', 'PUBLIC')
    from app.providers.x_oauth import XTokenClient
    from app.services.job_operations_service import JobOperationsService
    from app.services.job_dispatch_service import JobDispatchService
    from app.schemas.job_operations import ScheduleCreate
    c = x_context
    c.store.set_secret(c.ref, json.dumps({'schema_version': 1, 'access_token': 'test-only-old',
        'refresh_token': 'test-only-refresh', 'expires_at': OBS.isoformat()}))
    requests = []
    def mock(request):
        requests.append(request)
        if request.method == 'POST':
            return httpx.Response(200, json={'token_type': 'bearer', 'access_token': 'test-only-rotated',
                'refresh_token': 'test-only-rotated-refresh', 'expires_in': 7200})
        assert request.headers['Authorization'] == 'Bearer test-only-rotated'
        return httpx.Response(200, json=USER if request.url.path == '/2/users/me' else {'data': [post('100')]})
    client = ProviderHTTPClient(transport=httpx.MockTransport(mock))
    remote = XApiProvider(client, enabled=lambda: True)
    manager = XCredentialManager(c.factory, c.resolver, XTokenClient(c.source, client), enabled=lambda: True, now=lambda: OBS)
    handler = ProviderSyncHandler(c.factory, registry=ProviderRegistry({'X_API': lambda: (remote, XProviderNormalizer())}), resolver=manager, enabled=lambda: True)
    with c.factory() as s, s.begin():
        row = s.get(ProviderConnection, c.provider)
        row.connection_status = 'CONNECTED'
        row.capabilities = ['ACCOUNT_PROFILE', 'OWN_POSTS', 'OWN_METRICS']
    delivered = []
    ops = JobOperationsService(c.factory, enabled=lambda: True, clock=lambda: OBS,
        dispatcher=JobDispatchService(c.factory, publisher=delivered.append, enabled=lambda: True))
    schedule = ops.create_schedule(c.project, ScheduleCreate(provider_connection_id=c.provider,
        schedule_mode='INTERVAL', interval_seconds=60, enabled=True))
    assert ops.tick(now=OBS + timedelta(seconds=61)) == 1 and len(delivered) == 1
    assert JobRunner(c.jobs, handler).execute(delivered[0]) == 'SUCCESS'
    assert [r.method for r in requests] == ['POST', 'GET', 'GET']
    with c.factory() as s:
        job = s.get(JobRun, delivered[0])
        assert job.trigger_type == 'SCHEDULED' and job.job_schedule_id == schedule['id']
        metric = s.scalar(select(PostMetric).join(SNSPost).where(SNSPost.project_id == c.project))
        assert metric.recorded_at == job.scheduled_for
