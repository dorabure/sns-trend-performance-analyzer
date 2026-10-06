import json
from uuid import UUID, uuid4
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, func, update

from app.db.models import Project, ProviderConnection, ProviderSyncState, SNSAccount, SNSPost, ImportHistory
from app.providers.base import CsvDatasetType
from app.services.import_service import ImportFailure
from tests.providers.helpers import csv_text, row


def base(identifier):
    return f'/api/v1/projects/{identifier}'


@pytest.mark.parametrize('body,mode,count', [({}, 'DEMO', 0), ({'data_mode': 'DEMO'}, 'DEMO', 0), ({'data_mode': 'LIVE'}, 'LIVE', 2)])
def test_project_create_modes_and_atomic_provider_defaults(client, context, body, mode, count):
    result = client.post('/api/v1/projects', json={'name': 'New mode', 'platforms': ['X'], **body})
    assert result.status_code == 201
    data = result.json(); identifier = UUID(data['project_id'])
    assert data['data_mode'] == mode
    assert client.get(base(identifier)).json() == data
    assert data in client.get('/api/v1/projects').json()
    with context.factory() as session:
        providers = list(session.scalars(select(ProviderConnection).where(ProviderConnection.project_id == identifier)))
        assert len(providers) == count
        assert {p.provider_type for p in providers} == ({'X_API', 'INSTAGRAM_API'} if count else set())
        for p in providers:
            assert p.enabled is False and p.connection_status == 'NOT_CONFIGURED'
            assert p.credential_ref is None and p.remote_account_id is None and p.capabilities == []
            assert session.scalar(select(func.count()).select_from(ProviderSyncState).where(ProviderSyncState.provider_connection_id == p.id)) == 0
        for model in (SNSAccount, SNSPost, ImportHistory):
            assert session.scalar(select(func.count()).select_from(model).where(model.project_id == identifier)) == 0


@pytest.mark.parametrize('mode', ['INVALID', 'live', '', None, 1])
def test_invalid_mode_safe_validation(client, mode):
    result = client.post('/api/v1/projects', json={'name': 'Invalid', 'platforms': ['X'], 'data_mode': mode})
    assert result.status_code == 422 and result.json()['error']['code'] == 'VALIDATION_ERROR'


@pytest.mark.parametrize('method', ['patch', 'put'])
@pytest.mark.parametrize('mode', ['DEMO', 'LIVE'])
def test_mode_is_immutable_even_same_value(client, live, method, mode):
    response = getattr(client, method)(base(live), json={'data_mode': mode})
    assert response.status_code == 422
    assert client.get(base(live)).json()['data_mode'] == 'LIVE'


def test_context_and_demo_provider_boundary(client, context, live):
    demo = client.get(base(context.project_id) + '/context').json()
    assert demo['data_mode'] == 'DEMO' and demo['providers'] == []
    assert client.get(base(context.project_id) + '/providers').json() == []
    result = client.get(base(live) + '/context')
    assert result.status_code == 200 and 'data' not in result.json()
    assert result.json()['project_id'] == live and set(result.json()['platforms']) == {'X', 'INSTAGRAM'}
    assert len(result.json()['providers']) == 2
    for method in ('get', 'patch'):
        kwargs = {'json': {'enabled': True}} if method == 'patch' else {}
        denied = getattr(client, method)(base(context.project_id) + '/providers/X_API', **kwargs)
        assert denied.status_code == 409 and denied.json()['error']['code'] == 'PROVIDER_REQUIRES_LIVE'


@pytest.mark.parametrize('kind', ['X_API', 'INSTAGRAM_API'])
def test_enable_disable_never_claims_connection(client, context, live, kind):
    path = base(live) + '/providers/' + kind
    assert client.get(path).json()['sync_states'] == []
    for enabled, status in [(True, 'NOT_CONFIGURED'), (False, 'DISABLED'), (True, 'NOT_CONFIGURED')]:
        result = client.patch(path, json={'enabled': enabled})
        assert result.status_code == 200
        assert result.json()['enabled'] == enabled and result.json()['connection_status'] == status
    with context.factory() as session, session.begin():
        session.execute(update(ProviderConnection).where(ProviderConnection.project_id == UUID(live), ProviderConnection.provider_type == kind).values(connection_status='CONNECTED'))
    assert client.patch(path, json={'enabled': True}).json()['connection_status'] == 'NOT_CONFIGURED'


@pytest.mark.parametrize('body', [{}, {'enabled': None}, {'enabled': 'true'}, {'enabled': True, 'connection_status': 'CONNECTED'}, {'enabled': True, 'access_token': 'PRIVATE_DUMMY'}, {'enabled': True, 'credential_ref': 'X_PRIMARY'}, {'provider_type': 'X_API'}])
def test_provider_patch_only_enabled(client, live, body):
    result = client.patch(base(live) + '/providers/X_API', json=body)
    assert result.status_code == 422
    assert 'PRIVATE_DUMMY' not in result.text
    assert result.json()['error']['code'] == 'VALIDATION_ERROR'


@pytest.mark.parametrize('suffix', ['/context', '/providers', '/providers/X_API'])
def test_project_missing(client, suffix):
    result = client.get(base(uuid4()) + suffix)
    assert result.status_code == 404 and result.json()['error']['code'] == 'NOT_FOUND'


def test_missing_provider_and_invalid_provider_type(client, context, live):
    assert client.get(base(live) + '/providers/INVALID').status_code == 422
    assert client.patch(base(live) + '/providers/INVALID', json={'enabled': False}).status_code == 422
    # Scope must not fall back to another project's provider row.
    with context.factory() as s, s.begin():
        from sqlalchemy import delete
        s.execute(delete(ProviderConnection).where(ProviderConnection.project_id == UUID(live), ProviderConnection.provider_type == 'X_API'))
    assert client.get(base(live) + '/providers/X_API').status_code == 404


def test_detail_does_not_expose_internal_state(client, context, live):
    with context.factory() as s, s.begin():
        p = s.scalar(select(ProviderConnection).where(ProviderConnection.project_id == UUID(live), ProviderConnection.provider_type == 'X_API'))
        p.credential_ref = 'X_PRIMARY'
        s.add(ProviderSyncState(provider_connection_id=p.id, sync_resource_type='POSTS', cursor='internal-cursor', last_remote_id='123', state_json={'checkpoint': 'internal-value'}, last_synced_at=datetime.now(timezone.utc)))
    detail = client.get(base(live) + '/providers/X_API')
    assert detail.status_code == 200 and len(detail.json()['sync_states']) == 1
    serialized = json.dumps(detail.json())
    for value in ('credential_ref', 'X_PRIMARY', 'cursor', 'internal-cursor', 'state_json', 'internal-value', 'last_remote_id'):
        assert value not in serialized


@pytest.mark.parametrize('dataset', list(CsvDatasetType))
def test_live_csv_rejected_before_history_or_business_write(client, context, live, dataset):
    text = csv_text(dataset, [row(dataset)])
    response = client.post(base(live) + '/imports', data={'import_type': dataset.value}, files={'file': ('safe.csv', text.encode(), 'text/csv')})
    assert response.status_code == 409 and response.json()['errors'][0]['code'] == 'CSV_IMPORT_REQUIRES_DEMO'
    with context.factory() as s:
        for model in (ImportHistory, SNSPost, SNSAccount):
            assert s.scalar(select(func.count()).select_from(model).where(model.project_id == UUID(live))) == 0


def test_demo_import_origin_and_run_rechecks_mode(client, context, tmp_path):
    dataset = CsvDatasetType.OWN_POSTS
    text = csv_text(dataset, [row(dataset)])
    response = client.post(base(context.project_id) + '/imports', data={'import_type': dataset.value}, files={'file': ('demo.csv', text.encode(), 'text/csv')})
    assert response.status_code == 200 and response.json()['status'] == 'SUCCESS'
    with context.factory() as s:
        p = s.scalar(select(SNSPost).where(SNSPost.project_id == context.project_id))
        assert p.data_origin == 'DEMO_CSV' and p.provider_connection_id is None
    identifier, started = context.service.start(context.project_id, dataset, 'retry.csv')
    with context.factory() as s, s.begin():
        s.execute(update(Project).where(Project.project_id == context.project_id).values(data_mode='LIVE'))
    path = tmp_path / 'retry.csv'; path.write_text(text, encoding='utf-8')
    with pytest.raises(ImportFailure) as error:
        context.service.run(identifier, started, context.project_id, dataset, path)
    assert error.value.error.code == 'CSV_IMPORT_REQUIRES_DEMO'
    with context.factory() as s:
        assert s.get(ImportHistory, identifier).status == 'FAILED'


def test_live_manual_account_creation_rejected(client, live):
    result = client.post(base(live) + '/accounts', json={'platform': 'X', 'account_name': 'manual', 'account_role': 'OWN'})
    assert result.status_code == 409 and result.json()['error']['code'] == 'LIVE_ACCOUNT_REQUIRES_PROVIDER'


def test_creation_rolls_back_provider_failure(client, context, monkeypatch):
    from sqlalchemy import event
    def fail(mapper, connection, target):
        raise RuntimeError('PRIVATE SQL AND TOKEN MUST NOT LEAK')
    event.listen(ProviderConnection, 'before_insert', fail)
    try:
        response = client.post('/api/v1/projects', json={'name': 'Atomic failed', 'platforms': ['X'], 'data_mode': 'LIVE'})
        assert response.status_code == 500 and 'PRIVATE' not in response.text
        with context.factory() as s:
            assert s.scalar(select(Project).where(Project.name == 'Atomic failed')) is None
    finally:
        event.remove(ProviderConnection, 'before_insert', fail)


def test_provider_internal_failure_uses_safe_envelope(client, live, monkeypatch):
    from app.repositories.provider_repository import ProviderRepository
    def fail(*args, **kwargs):
        raise RuntimeError('PRIVATE sql token traceback')
    monkeypatch.setattr(ProviderRepository, 'connections', fail)
    response = client.get(base(live) + '/providers')
    assert response.status_code == 500 and response.json()['error']['code'] == 'SETTINGS_ERROR'
    assert 'PRIVATE' not in response.text
