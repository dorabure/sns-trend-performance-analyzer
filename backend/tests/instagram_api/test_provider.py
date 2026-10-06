from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4
import httpx
import pytest
from fastapi.testclient import TestClient
from app.providers.core import ProviderError, ProviderCredential, ProviderContext, ProviderRegistry, ProviderCapability
from app.providers.http_client import ProviderHTTPClient
from app.providers.instagram_api_provider import InstagramApiProvider, InstagramProviderNormalizer
from app.providers.instagram_oauth import InstagramCredentialManager, token_payload
from app.providers.credential_manager import CredentialManagerRouter
from app.db.models import JobRun, ProviderConnection, ProviderSyncState, SNSPost
from app.jobs.runner import JobRunner
from app.services.provider_sync_handler import ProviderSyncHandler
from app.main import app
from sqlalchemy import select, func
import json

NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)
PROFILE = {'id': '999', 'user_id': '111', 'username': 'test.own', 'name': 'Fixture',
    'account_type': 'Business', 'followers_count': 0, 'follows_count': 2, 'media_count': 5}


@pytest.mark.parametrize('envelope', [False, True])
def test_profile_canonical_id_zero_null_and_normalization(envelope):
    data = dict(PROFILE); data.pop('follows_count')
    account = InstagramApiProvider.account({'data': [data]} if envelope else data, NOW)
    assert account.remote_account_id == '111' and account.metrics.values == {'followers': 0, 'following': None, 'post_count': 5}
    profile, metric = InstagramProviderNormalizer().normalize_account(account, NOW)
    assert profile.platform == 'INSTAGRAM' and metric.followers == 0 and metric.following is None
    assert profile.profile_url == 'https://www.instagram.com/test.own/'


@pytest.mark.parametrize('changes,expected', [({'user_id': None}, 'PROVIDER_RESPONSE_INVALID'),
    ({'user_id': 111}, 'PROVIDER_RESPONSE_INVALID'), ({'user_id': '../1'}, 'PROVIDER_RESPONSE_INVALID'),
    ({'username': 'bad/name'}, 'PROVIDER_RESPONSE_INVALID'), ({'account_type': 'PERSONAL'}, 'PROVIDER_SCOPE_INVALID'),
    ({'followers_count': True}, 'PROVIDER_RESPONSE_INVALID'), ({'media_count': -1}, 'PROVIDER_RESPONSE_INVALID'),
    ({'name': []}, 'PROVIDER_RESPONSE_INVALID')])
def test_invalid_profile(changes, expected):
    with pytest.raises(ProviderError, match=expected): InstagramApiProvider.account(dict(PROFILE, **changes), NOW)


@pytest.mark.parametrize('raw', [{'data': []}, {'data': [PROFILE, PROFILE]}, {'error': {'message': 'private'}}, []])
def test_invalid_profile_envelope(raw):
    with pytest.raises(ProviderError, match='PROVIDER_RESPONSE_INVALID'): InstagramApiProvider.account(raw)


@pytest.mark.parametrize('live,smoke', [('false', 'false'), ('false', 'true'), ('true', 'false')])
def test_profile_gate_zero_requests(monkeypatch, live, smoke):
    monkeypatch.setenv('LIVE_MODE_ENABLED', live); monkeypatch.setenv('INSTAGRAM_LIVE_SMOKE_ENABLED', smoke)
    remote = InstagramApiProvider(ProviderHTTPClient(transport=httpx.MockTransport(lambda _: pytest.fail('network'))))
    with pytest.raises(ProviderError, match='INSTAGRAM_LIVE_SMOKE_DISABLED'): remote.validate_connection(ProviderCredential('test-only'))


@pytest.mark.parametrize('version', ['', 'latest', '../v26.0', 'v26.0?access_token=private'])
def test_invalid_version_no_requests(monkeypatch, version):
    monkeypatch.setenv('INSTAGRAM_GRAPH_API_VERSION', version)
    remote = InstagramApiProvider(ProviderHTTPClient(transport=httpx.MockTransport(lambda _: pytest.fail('network'))), enabled=lambda: True)
    with pytest.raises(ProviderError, match='PROVIDER_NOT_CONFIGURED'): remote.validate_connection(ProviderCredential('test-only'))


def test_validate_profile_only_and_posts_blocked_no_insights():
    calls = []
    def mock(request): calls.append(request); return httpx.Response(200, json=PROFILE)
    remote = InstagramApiProvider(ProviderHTTPClient(transport=httpx.MockTransport(mock)), enabled=lambda: True)
    credential = ProviderCredential('test-only')
    assert remote.validate_connection(credential).remote_account_id == '111'
    assert len(calls) == 1 and calls[0].url.path == '/v26.0/me' and calls[0].url.host == 'graph.instagram.com'
    assert 'access_token' not in calls[0].url.params and calls[0].headers['Authorization'] == 'Bearer test-only'
    context = ProviderContext(uuid4(), uuid4(), credential, NOW)
    with pytest.raises(ProviderError, match='INSTAGRAM_SPEC_UNVERIFIED'): remote.fetch_posts(context, remote.account(PROFILE, NOW))
    assert len(calls) == 1


@pytest.mark.parametrize('stored', [[], ['ACCOUNT_PROFILE', 'OWN_POSTS', 'OWN_METRICS']])
def test_production_capabilities_api_and_profile_validate(instagram_context, stored):
    from app.api.v1.providers import get_provider_service
    from app.services.provider_service import ProviderService
    c = instagram_context
    c.store.set_secret(c.ref, json.dumps(token_payload({'access_token': 'test-only', 'token_type': 'bearer', 'expires_in': 5184000}, NOW)))
    with c.factory() as session, session.begin():
        session.get(ProviderConnection, c.provider).capabilities = stored
    calls = []
    def mock(request):
        calls.append(request)
        return httpx.Response(200, json=PROFILE)
    remote = InstagramApiProvider(ProviderHTTPClient(transport=httpx.MockTransport(mock)), enabled=lambda: True)
    assert remote.capabilities() == {ProviderCapability.ACCOUNT_PROFILE}
    registry = ProviderRegistry({'INSTAGRAM_API': lambda: (remote, InstagramProviderNormalizer())})
    service = ProviderService(c.factory, registry=registry, resolver=c.resolver, enabled=lambda: True)
    app.dependency_overrides[get_provider_service] = lambda: service
    try:
        with TestClient(app) as client:
            base = f'/api/v1/projects/{c.project}/providers/INSTAGRAM_API'
            result = client.get(base + '/capabilities')
            assert result.status_code == 200
            caps = result.json()['capabilities']
            assert caps['ACCOUNT_PROFILE'] is True
            assert caps['OWN_POSTS'] is False and caps['OWN_METRICS'] is False
            assert not calls  # Capability discovery never resolves credentials or calls Meta.
            for response in [client.get(base), client.get(f'/api/v1/projects/{c.project}/providers')]:
                assert response.status_code == 200
                row = response.json() if isinstance(response.json(), dict) else response.json()[0]
                assert 'OWN_POSTS' not in row['capabilities'] and 'OWN_METRICS' not in row['capabilities']
            with c.factory() as session:
                assert session.get(ProviderConnection, c.provider).capabilities == sorted(stored)
            result = client.post(base + '/validate')
            assert result.status_code == 200 and result.json()['valid'] is True
            assert result.json()['connection_status'] == 'CONNECTED'
            assert result.json()['capabilities'] == ['ACCOUNT_PROFILE']
            assert len(calls) == 1 and calls[0].url.path == '/v26.0/me'
        with c.factory() as session:
            assert session.get(ProviderConnection, c.provider).capabilities == ['ACCOUNT_PROFILE']
    finally:
        app.dependency_overrides.pop(get_provider_service, None)


def test_profile_capability_required_for_validation(instagram_context):
    from app.services.provider_service import ProviderService
    from app.services.settings_service import SettingsFailure
    c = instagram_context
    c.store.set_secret(c.ref, json.dumps(token_payload({'access_token': 'test-only', 'token_type': 'bearer', 'expires_in': 5184000}, NOW)))
    remote = InstagramApiProvider(ProviderHTTPClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json=PROFILE))), enabled=lambda: True)
    remote.capabilities = lambda: set()
    registry = ProviderRegistry({'INSTAGRAM_API': lambda: (remote, InstagramProviderNormalizer())})
    with pytest.raises(SettingsFailure) as error:
        ProviderService(c.factory, registry=registry, resolver=c.resolver, enabled=lambda: True).validate(c.project, 'INSTAGRAM_API')
    assert error.value.code == 'PROVIDER_CAPABILITY_UNAVAILABLE'


def test_pipeline_spec_block_preserves_business_and_checkpoint(instagram_context):
    c = instagram_context
    c.store.set_secret(c.ref, json.dumps(token_payload({'access_token': 'test-only', 'token_type': 'bearer', 'expires_in': 5184000}, NOW)))
    calls = []
    def mock(request): calls.append(request); return httpx.Response(200, json=PROFILE)
    remote = InstagramApiProvider(ProviderHTTPClient(transport=httpx.MockTransport(mock)), enabled=lambda: True)
    manager = InstagramCredentialManager(c.factory, c.resolver, enabled=lambda: True, now=lambda: NOW)
    handler = ProviderSyncHandler(c.factory, registry=ProviderRegistry({'INSTAGRAM_API': lambda: (remote, InstagramProviderNormalizer())}),
        resolver=CredentialManagerRouter(c.factory, instagram_manager=manager), enabled=lambda: True)
    jid = c.jobs.create(c.project, 'LIVE', c.provider)
    JobRunner(c.jobs, handler).execute(jid)
    with c.factory() as session:
        job = session.get(JobRun, jid)
        assert job.status == 'FAILED' and job.error_code == 'INSTAGRAM_SPEC_UNVERIFIED'
        assert session.scalar(select(func.count()).select_from(ProviderSyncState).where(ProviderSyncState.provider_connection_id == c.provider)) == 0
        assert session.scalar(select(func.count()).select_from(SNSPost).where(SNSPost.project_id == c.project)) == 0
    assert not calls


def test_oauth_api_paths_and_disabled_responses(monkeypatch):
    monkeypatch.setenv('LIVE_MODE_ENABLED', 'false'); monkeypatch.setenv('INSTAGRAM_OAUTH_BOOTSTRAP_ENABLED', 'false')
    with TestClient(app) as client:
        paths = client.get('/openapi.json').json()['paths']
        # Later phases may add unrelated API paths; retain the Instagram contract.
        assert len(paths) >= 44 and not any(p.startswith('/api/v2') for p in paths)
        assert '/api/v1/projects/{project_id}/providers/INSTAGRAM_API/oauth/start' in paths
        for url in [f'/api/v1/projects/{uuid4()}/providers/INSTAGRAM_API/oauth/start',
                    '/api/v1/providers/INSTAGRAM_API/oauth/callback?code=private&state=private']:
            response = client.post(url) if url.endswith('/start') else client.get(url)
            assert response.status_code == 409 and response.json()['error']['code'] == 'OAUTH_DISABLED'
            assert 'private' not in response.text
