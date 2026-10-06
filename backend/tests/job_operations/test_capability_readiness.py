from datetime import timedelta
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.db.models import ProviderConnection, JobSchedule, JobRun
from app.providers.core import ProviderRegistry
from app.providers.readiness import sync_capabilities_available
from app.schemas.job_operations import ScheduleCreate, SchedulePatch
from app.services.job_operations_service import OperationsFailure
from tests.job_operations.test_operations import NOW, create, due

CAPS = ['ACCOUNT_PROFILE', 'OWN_POSTS', 'OWN_METRICS']


@pytest.mark.parametrize('current,stored,expected', [
    (CAPS, CAPS, True), (['ACCOUNT_PROFILE'], CAPS, False),
    (CAPS, ['ACCOUNT_PROFILE', 'OWN_METRICS'], False), (CAPS, [], False),
    (CAPS, None, False), (CAPS, ['INVALID'], False), (CAPS, CAPS + ['OWN_POSTS'], False),
    (['ACCOUNT_PROFILE'], ['ACCOUNT_PROFILE'], False),
])
def test_capability_intersection_fail_closed(current, stored, expected):
    remote = SimpleNamespace(provider_type='X_API', capabilities=lambda: current)
    registry = ProviderRegistry({'X_API': lambda: (remote, None)})
    assert sync_capabilities_available(SimpleNamespace(provider_type='X_API', capabilities=stored), registry) is expected


@pytest.mark.parametrize('stored', [['ACCOUNT_PROFILE'], CAPS])
def test_instagram_direct_endpoints_reject_without_job(ops, stored):
    from app.main import app
    from app.api.v1.job_operations import get_operations_service
    with ops.factory() as s, s.begin():
        s.get(ProviderConnection, ops.second).capabilities = stored
        row = JobSchedule(project_id=ops.pid, provider_connection_id=ops.second,
            schedule_scope_key=f'fixture:{ops.second}', schedule_mode='INTERVAL', interval_seconds=60,
            schedule_type='PROVIDER_SYNC_PIPELINE', enabled=True, next_run_at=NOW)
        s.add(row); s.flush(); sid = str(row.id)
    app.dependency_overrides[get_operations_service] = lambda: ops.service
    try:
        with TestClient(app) as client:
            base = f'/api/v1/projects/{ops.pid}'
            for enabled in (False, True):
                response = client.post(base+'/schedules', json=dict(provider_connection_id=str(ops.second),
                    schedule_mode='INTERVAL', interval_seconds=60, enabled=enabled))
                assert response.status_code == 409
                assert response.json()['error']['code'] == 'PROVIDER_CAPABILITY_UNAVAILABLE'
            for path in ('/providers/INSTAGRAM_API/sync', f'/schedules/{sid}/enable', f'/schedules/{sid}/run-now'):
                response = client.post(base+path)
                assert response.status_code == 409
                assert response.json()['error']['code'] == 'PROVIDER_CAPABILITY_UNAVAILABLE'
            response = client.patch(base+f'/schedules/{sid}', json={'interval_seconds': 120})
            assert response.status_code == 409 and response.json()['error']['code'] == 'PROVIDER_CAPABILITY_UNAVAILABLE'
            assert ops.service.tick(NOW) == 0
            assert ops.service.get_schedule(ops.pid, row.id)['next_run_at'] == NOW+timedelta(seconds=60)
            assert ops.service.tick(NOW) == 0
            assert ops.service.list_jobs(ops.pid)['total'] == 0 and not ops.calls
            assert client.post(base+f'/schedules/{sid}/disable').status_code == 200
            assert client.delete(base+f'/schedules/{sid}').status_code == 204
    finally:
        app.dependency_overrides.pop(get_operations_service, None)


def test_unconfigured_x_disabled_creation_remains_possible(ops):
    with ops.factory() as s, s.begin():
        provider = s.get(ProviderConnection, ops.provider)
        provider.connection_status, provider.capabilities = 'NOT_CONFIGURED', []
    row = create(ops)
    with pytest.raises(OperationsFailure) as error:
        ops.service.set_enabled(ops.pid, row['id'], True)
    assert error.value.code == 'PROVIDER_NOT_READY'
    assert not ops.service.get_schedule(ops.pid, row['id'])['enabled']


@pytest.mark.parametrize('loss', ['current', 'stored'])
def test_x_capability_loss_stops_acceptance_but_allows_cleanup(ops, loss):
    sid = due(ops)
    if loss == 'current':
        from app.providers.x_api_provider import XApiProvider
        remote = XApiProvider()
        remote.capabilities = lambda: {'ACCOUNT_PROFILE'}
        ops.service.registry = ProviderRegistry({'X_API': lambda: (remote, None)})
    else:
        with ops.factory() as s, s.begin():
            s.get(ProviderConnection, ops.provider).capabilities = ['ACCOUNT_PROFILE', 'OWN_METRICS']
    for action in (lambda: ops.service.sync(ops.pid, 'X_API'), lambda: ops.service.run_now(ops.pid, sid),
        lambda: ops.service.set_enabled(ops.pid, sid, True),
        lambda: ops.service.patch_schedule(ops.pid, sid, SchedulePatch(interval_seconds=120))):
        with pytest.raises(OperationsFailure) as error: action()
        assert error.value.code == 'PROVIDER_CAPABILITY_UNAVAILABLE'
    assert ops.service.tick(NOW) == 0
    row = ops.service.get_schedule(ops.pid, sid)
    assert row['enabled'] and row['next_run_at'] == NOW+timedelta(seconds=60)
    assert row['last_run_at'] is None and row['last_job_run_id'] is None
    assert ops.service.tick(NOW) == 0 and ops.service.list_jobs(ops.pid)['total'] == 0
    assert ops.service.set_enabled(ops.pid, sid, False)['next_run_at'] is None
    ops.service.delete_schedule(ops.pid, sid)
