from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, insert, select, func

from app.db.models import Project, ProviderConnection, ProviderSyncState, SNSAccount, SNSPost
from tests.test_database import add, rejects


@pytest.fixture
def provider(database):
    p = add(database, Project, name='DB live', data_mode='LIVE')
    return add(database, ProviderConnection, project_id=p['project_id'], provider_type='X_API')


@pytest.mark.parametrize('model,field,invalid', [
    (ProviderConnection, 'provider_type', 'CSV'),
    (ProviderConnection, 'connection_status', 'SYNCING'),
    (ProviderConnection, 'connection_status', 'INVALID'),
    (ProviderConnection, 'last_record_count', -1),
    (ProviderSyncState, 'sync_resource_type', 'INVALID'),
    (ProviderSyncState, 'last_record_count', -1),
    (Project, 'data_mode', 'INVALID'),
    (SNSAccount, 'data_origin', 'INVALID'),
    (SNSPost, 'data_origin', 'INVALID'),
])
def test_invalid_db_enums_and_counts(database, provider, model, field, invalid):
    project = provider['project_id']
    values = {
        Project: {'name': 'bad'},
        ProviderConnection: {'project_id': project, 'provider_type': 'INSTAGRAM_API'},
        ProviderSyncState: {'provider_connection_id': provider['id'], 'sync_resource_type': 'POSTS'},
        SNSAccount: {'project_id': project, 'platform': 'X', 'account_name': 'bad', 'account_role': 'OWN'},
        SNSPost: {'project_id': project, 'platform': 'X', 'source_type': 'OWN', 'platform_post_id': 'bad', 'posted_at': datetime.now(timezone.utc)},
    }[model]
    rejects(database, lambda: add(database, model, **{**values, field: invalid}), '23514')


def test_defaults_uniques_and_resource_types(database, provider):
    assert provider['enabled'] is False and provider['connection_status'] == 'NOT_CONFIGURED'
    assert provider['last_record_count'] == 0 and provider['capabilities'] == []
    assert provider['credential_ref'] is None
    rejects(database, lambda: add(database, ProviderConnection, project_id=provider['project_id'], provider_type='X_API'), '23505')
    for resource in ('ACCOUNT', 'POSTS', 'METRICS', 'INSIGHTS'):
        state = add(database, ProviderSyncState, provider_connection_id=provider['id'], sync_resource_type=resource)
        assert state['state_json'] == {} and state['last_record_count'] == 0
        assert state['cursor'] is None and state['last_remote_id'] is None
        rejects(database, lambda r=resource: add(database, ProviderSyncState, provider_connection_id=provider['id'], sync_resource_type=r), '23505')


@pytest.mark.parametrize('status', ['NOT_CONFIGURED', 'CONNECTED', 'ERROR', 'DISABLED'])
def test_valid_connection_status(database, provider, status):
    database.execute(ProviderConnection.__table__.update().values(connection_status=status))
    assert database.scalar(select(ProviderConnection.connection_status)) == status


def test_provider_delete_cascade_and_business_set_null(database, provider):
    pid, connection = provider['project_id'], provider['id']
    account = add(database, SNSAccount, project_id=pid, platform='X', account_name='live', account_role='OWN', data_origin='X_API', provider_connection_id=connection)
    post = add(database, SNSPost, project_id=pid, account_id=account['account_id'], platform='X', source_type='OWN', platform_post_id='stable-id', posted_at=datetime.now(timezone.utc), data_origin='X_API', provider_connection_id=connection)
    add(database, ProviderSyncState, provider_connection_id=connection, sync_resource_type='POSTS')
    database.execute(delete(ProviderConnection).where(ProviderConnection.id == connection))
    assert database.scalar(select(func.count()).select_from(ProviderSyncState)) == 0
    assert database.scalar(select(SNSAccount.provider_connection_id)) is None
    assert database.scalar(select(SNSPost.provider_connection_id)) is None
    assert database.scalar(select(SNSPost.data_origin)) == 'X_API'
    rejects(database, lambda: add(database, SNSPost, project_id=pid, platform='X', source_type='MARKET', platform_post_id='stable-id', posted_at=post['posted_at']), '23505')


def test_project_delete_cascades_provider_and_state(database, provider):
    add(database, ProviderSyncState, provider_connection_id=provider['id'], sync_resource_type='ACCOUNT')
    database.execute(delete(Project).where(Project.project_id == provider['project_id']))
    for table in (ProviderConnection, ProviderSyncState):
        assert database.scalar(select(func.count()).select_from(table)) == 0


@pytest.mark.parametrize('payload', [
    {'access_token': 'PRIVATE_DUMMY'}, {'nested': [{'refreshToken': 'PRIVATE_DUMMY'}]},
    {'client_secret': 'PRIVATE_DUMMY'}, {'Authorization': 'PRIVATE_DUMMY'},
    {'openai_api_key': 'PRIVATE_DUMMY'}, {'secret_json': {}},
    {'note': 'Bearer PRIVATE_DUMMY'}, {'note': 'sk-proj-PRIVATE_DUMMY'},
])
def test_state_rejects_nested_secret_metadata(database, provider, payload):
    with pytest.raises(ValueError, match='Credentials are not allowed') as error:
        database.add(ProviderSyncState(provider_connection_id=provider['id'], sync_resource_type='POSTS', state_json=payload))
        database.flush()
    assert 'PRIVATE_DUMMY' not in str(error.value)
    assert database.scalar(select(func.count()).select_from(ProviderSyncState)) == 0


@pytest.mark.parametrize('value', ['Bearer PRIVATE_DUMMY', 'sk-proj-PRIVATE_DUMMY', '{"access_token":"dummy"}', 'spaces are invalid'])
def test_credential_ref_is_identifier_only(database, provider, value):
    with pytest.raises(ValueError, match='logical identifier'):
        ProviderConnection(project_id=provider['project_id'], provider_type='INSTAGRAM_API', credential_ref=value)


def test_safe_state_metadata_and_reference(database, provider):
    state = ProviderSyncState(provider_connection_id=provider['id'], sync_resource_type='POSTS', state_json={'version': 1, 'checkpoint': {'completed': True}})
    database.add(state); database.flush()
    assert state.state_json['version'] == 1
    connection = database.get(ProviderConnection, provider['id'])
    connection.credential_ref = 'X_PRIMARY'
    database.flush()
    assert connection.credential_ref == 'X_PRIMARY'


def test_state_in_place_secret_mutation_rejected_at_flush(database, provider):
    from sqlalchemy.orm.attributes import flag_modified
    state = ProviderSyncState(provider_connection_id=provider['id'], sync_resource_type='POSTS', state_json={'version': 1})
    database.add(state)
    database.flush()
    state.state_json['nested'] = {'access_token': 'PRIVATE_DUMMY'}
    flag_modified(state, 'state_json')
    with pytest.raises(ValueError, match='Credentials are not allowed') as error:
        database.flush()
    assert 'PRIVATE_DUMMY' not in str(error.value)
