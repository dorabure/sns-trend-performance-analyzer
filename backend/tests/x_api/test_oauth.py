import base64
import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
import httpx
import pytest
from sqlalchemy import select
from app.db.models import ProviderConnection, Project, JobRun
from app.providers.core import ProviderError, ProviderRegistry
from app.providers.http_client import ProviderHTTPClient
from app.providers.x_oauth import XOAuthService, XCredentialManager, XTokenClient, SCOPES
from app.providers.x_api_provider import XApiProvider, XProviderNormalizer
from app.core.oauth_log_filter import OAuthAccessFilter
from app.services.provider_sync_handler import ProviderSyncHandler
from app.jobs.runner import JobRunner
from tests.x_api.test_provider import OBS

REDIRECT = 'http://127.0.0.1:8000/api/v1/providers/X_API/oauth/callback'


@pytest.fixture(autouse=True)
def oauth_config(monkeypatch):
    monkeypatch.setenv('X_OAUTH_CLIENT_TYPE', 'PUBLIC')
    monkeypatch.setenv('X_OAUTH_REDIRECT_URI', REDIRECT)


def tokens(**changes):
    return dict({'token_type': 'bearer', 'expires_in': 7200, 'scope': ' '.join(SCOPES),
        'access_token': 'test-only-new-access', 'refresh_token': 'test-only-new-refresh'}, **changes)


def setup(c, response=None):
    calls = []
    def mock(request):
        calls.append(request)
        return response if isinstance(response, httpx.Response) else httpx.Response(200, json=tokens() if response is None else response)
    token_client = XTokenClient(c.source, ProviderHTTPClient(transport=httpx.MockTransport(mock)))
    service = XOAuthService(c.factory, c.resolver, token_client, enabled=lambda: True, now=lambda: OBS)
    return service, calls, token_client


def pending(c, service):
    result = service.start(c.project)
    query = parse_qs(urlsplit(result['authorize_url']).query)
    state = query['state'][0]
    name = service.pending_name(state)
    return state, name, json.loads(c.store.get_secret(name)), query


def test_pkce_encrypted_callback_rotation_and_replay(x_context, caplog):
    c = x_context; service, calls, _ = setup(c)
    state, name, record, query = pending(c, service)
    assert query['code_challenge_method'] == ['S256'] and set(query['scope'][0].split()) == set(SCOPES)
    verifier = record['code_verifier']
    assert query['code_challenge'] == [base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()]
    ciphertext = c.store.path(name).read_bytes()
    assert state.encode() not in ciphertext and verifier.encode() not in ciphertext
    assert record['redirect_uri'] == REDIRECT
    result = service.callback(state=state, code='test-only-code')
    assert result == {'provider_type': 'X_API', 'authorized': True} and len(calls) == 1
    request = calls[0]
    assert request.method == 'POST' and str(request.url) == 'https://api.x.com/2/oauth2/token'
    form = parse_qs(request.content.decode())
    assert form['grant_type'] == ['authorization_code'] and form['code_verifier'] == [verifier]
    assert form['redirect_uri'] == [REDIRECT] and form['client_id'] == ['test-only-client']
    assert 'Authorization' not in request.headers
    assert c.store.get_secret(name) is None
    credential = c.resolver.resolve('X_API', c.ref)
    assert credential.access_token == 'test-only-new-access' and credential.refresh_token == 'test-only-new-refresh'
    assert not caplog.text and 'test-only' not in repr(credential)
    with pytest.raises(ProviderError, match='OAUTH_STATE_INVALID'):
        service.callback(state=state, code='test-only-code')
    assert len(calls) == 1
    with c.factory() as s:
        row = s.get(ProviderConnection, c.provider)
        assert row.enabled and row.connection_status == 'NOT_CONFIGURED'


@pytest.mark.parametrize('scenario,expected', [('wrong_state', 'OAUTH_STATE_INVALID'), ('expired', 'OAUTH_STATE_EXPIRED'),
    ('missing_code', 'OAUTH_STATE_INVALID'), ('denied', 'OAUTH_STATE_INVALID'), ('provider_mismatch', 'OAUTH_PROVIDER_INVALID'),
    ('project_mismatch', 'OAUTH_PROVIDER_INVALID'), ('redirect_changed', 'OAUTH_STATE_INVALID')])
def test_invalid_callback_no_exchange(x_context, monkeypatch, scenario, expected):
    c = x_context; service, calls, _ = setup(c)
    state, name, record, _ = pending(c, service)
    code, error = 'test-only-code', None
    if scenario == 'wrong_state': state = 'x' * 43
    if scenario == 'expired': record['expires_at'] = (OBS - timedelta(seconds=1)).isoformat()
    if scenario == 'provider_mismatch': record['provider_connection_id'] = str(uuid4())
    if scenario == 'project_mismatch': record['project_id'] = str(uuid4())
    if scenario == 'missing_code': code = None
    if scenario == 'denied': error = 'access_denied'
    if scenario == 'redirect_changed': monkeypatch.setenv('X_OAUTH_REDIRECT_URI', REDIRECT.replace('127.0.0.1', 'localhost'))
    c.store.set_secret(name, json.dumps(record))
    with pytest.raises(ProviderError, match=expected):
        service.callback(state=state, code=code, error=error)
    assert calls == [] and c.store.get_secret(c.ref) is None


@pytest.mark.parametrize('state', [None, '', 'short', '../' * 20, 'é' * 50, 'x' * 129])
def test_invalid_state_format_rejects(x_context, state):
    service, calls, _ = setup(x_context)
    with pytest.raises(ProviderError, match='OAUTH_STATE_INVALID'):
        service.callback(state=state, code='test-only-code')
    assert not calls


@pytest.mark.parametrize('uri', ['https://evil.invalid/api/v1/providers/X_API/oauth/callback', REDIRECT + '?evil=1',
    REDIRECT + '#fragment', REDIRECT.replace('127.0.0.1', 'user:password@127.0.0.1'), REDIRECT + '/extra'])
def test_redirect_fixed_local_only(x_context, monkeypatch, uri):
    monkeypatch.setenv('X_OAUTH_REDIRECT_URI', uri)
    service, calls, _ = setup(x_context)
    with pytest.raises(ProviderError, match='PROVIDER_NOT_CONFIGURED'):
        service.start(x_context.project)
    assert not calls


@pytest.mark.parametrize('live,oauth', [('false', 'false'), ('true', 'false'), ('false', 'true')])
def test_oauth_gate_closed(x_context, monkeypatch, live, oauth):
    monkeypatch.setenv('LIVE_MODE_ENABLED', live); monkeypatch.setenv('X_OAUTH_BOOTSTRAP_ENABLED', oauth)
    service = XOAuthService(x_context.factory, x_context.resolver)
    with pytest.raises(ProviderError, match='OAUTH_DISABLED'):
        service.start(x_context.project)


@pytest.mark.parametrize('client_type', ['', 'OTHER'])
def test_client_type_requires_explicit_selection(x_context, monkeypatch, client_type):
    monkeypatch.setenv('X_OAUTH_CLIENT_TYPE', client_type)
    service, calls, _ = setup(x_context)
    with pytest.raises(ProviderError, match='PROVIDER_NOT_CONFIGURED'):
        service.start(x_context.project)
    assert not calls


def test_confidential_basic_no_secret_in_form(x_context, monkeypatch):
    monkeypatch.setenv('X_OAUTH_CLIENT_TYPE', 'CONFIDENTIAL')
    service, calls, _ = setup(x_context)
    state, _, _, _ = pending(x_context, service)
    service.callback(state=state, code='test-only-code')
    assert calls[0].headers['Authorization'] == 'Basic ' + base64.b64encode(b'test-only-client:test-only-client-secret').decode()
    assert 'client_secret' not in parse_qs(calls[0].content.decode())


@pytest.mark.parametrize('response,expected', [(tokens(scope='tweet.read users.read'), 'OAUTH_SCOPE_INSUFFICIENT'),
    (tokens(refresh_token=None), 'PROVIDER_RESPONSE_INVALID'), (tokens(expires_in=True), 'PROVIDER_RESPONSE_INVALID'),
    (tokens(token_type='other'), 'PROVIDER_RESPONSE_INVALID'), (httpx.Response(400, json={'error': 'invalid_grant'}), 'PROVIDER_AUTH_FAILED'),
    (httpx.Response(401, json={'secret': 'private'}), 'PROVIDER_AUTH_FAILED'), (httpx.Response(500), 'PROVIDER_SERVER_ERROR')])
def test_token_errors_safe_and_no_replay(x_context, response, expected, caplog):
    c = x_context; service, calls, _ = setup(c, response)
    state, name, _, _ = pending(c, service)
    with pytest.raises(ProviderError, match=expected):
        service.callback(state=state, code='test-only-code')
    assert len(calls) == 1 and c.store.get_secret(c.ref) is None and c.store.get_secret(name) is None
    assert not caplog.text


def test_token_timeout_one_attempt(x_context):
    calls = []
    def fail(request):
        calls.append(1); raise httpx.ReadTimeout('test-only-private')
    client = XTokenClient(x_context.source, ProviderHTTPClient(transport=httpx.MockTransport(fail)))
    with pytest.raises(ProviderError, match='PROVIDER_TIMEOUT'):
        client.exchange({'grant_type': 'refresh_token', 'refresh_token': 'test-only-refresh'})
    assert len(calls) == 1


def expired(c):
    c.store.set_secret(c.ref, json.dumps({'schema_version': 1, 'access_token': 'test-only-old-access',
        'refresh_token': 'test-only-old-refresh', 'expires_at': (OBS - timedelta(seconds=1)).isoformat()}))


def test_refresh_two_workers_one_call_both_new_credentials(x_context):
    c = x_context; expired(c)
    _, calls, client = setup(c)
    manager = XCredentialManager(c.factory, c.resolver, client, enabled=lambda: True, now=lambda: OBS)
    barrier = Barrier(2)
    def resolve():
        with c.factory() as s:
            row = s.get(ProviderConnection, c.provider)
            barrier.wait(timeout=10)
            return manager.resolve_connection(row)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: resolve(), range(2)))
    assert len(calls) == 1 and all(r.access_token == 'test-only-new-access' for r in results)
    assert all(r.refresh_token == 'test-only-new-refresh' for r in results)
    assert parse_qs(calls[0].content.decode())['refresh_token'] == ['test-only-old-refresh']
    assert c.resolver.resolve('X_API', c.ref).access_token == 'test-only-new-access'


def test_refresh_missing_refresh_token_retains_previous(x_context):
    c = x_context; expired(c)
    response = tokens(); response.pop('refresh_token'); response.pop('scope')
    _, calls, client = setup(c, response)
    manager = XCredentialManager(c.factory, c.resolver, client, enabled=lambda: True, now=lambda: OBS)
    with c.factory() as s:
        result = manager.resolve_connection(s.get(ProviderConnection, c.provider))
    assert result.refresh_token == 'test-only-old-refresh' and len(calls) == 1


def test_not_expiring_no_refresh(x_context):
    c = x_context; _, calls, client = setup(c)
    manager = XCredentialManager(c.factory, c.resolver, client, enabled=lambda: True, now=lambda: OBS)
    with c.factory() as s:
        result = manager.resolve_connection(s.get(ProviderConnection, c.provider))
    assert result.access_token == 'test-only-access' and not calls


def test_refresh_invalid_grant_preserves_cipher_and_fails_provider_job(x_context):
    c = x_context; expired(c)
    original = c.store.path(c.ref).read_bytes()
    _, calls, client = setup(c, httpx.Response(400, json={'error': 'invalid_grant', 'detail': 'private'}))
    manager = XCredentialManager(c.factory, c.resolver, client, enabled=lambda: True, now=lambda: OBS)
    remote = XApiProvider(ProviderHTTPClient(transport=httpx.MockTransport(lambda _: pytest.fail('no reads after failed refresh'))), enabled=lambda: True)
    handler = ProviderSyncHandler(c.factory, registry=ProviderRegistry({'X_API': lambda: (remote, XProviderNormalizer())}),
        resolver=manager, enabled=lambda: True)
    jid = c.jobs.create(c.project, 'LIVE', c.provider)
    assert JobRunner(c.jobs, handler).execute(jid) == 'FAILED'
    assert len(calls) == 1 and c.store.path(c.ref).read_bytes() == original
    with c.factory() as s:
        assert s.get(JobRun, jid).error_code == 'PROVIDER_AUTH_FAILED'
        assert s.get(ProviderConnection, c.provider).connection_status == 'ERROR'


def test_access_log_callback_query_redacted():
    record = logging.LogRecord('uvicorn.access', logging.INFO, '', 1, '%s %s %s %s %s',
        ('client', 'GET', '/api/v1/providers/X_API/oauth/callback?code=test-only-code&state=test-only-state', '1.1', 200), None)
    assert OAuthAccessFilter().filter(record)
    assert '?' not in record.getMessage() and 'test-only' not in record.getMessage()


def test_concurrent_callback_once(x_context):
    c = x_context; service, calls, _ = setup(c)
    state, _, _, _ = pending(c, service)
    barrier = Barrier(2)
    def invoke():
        barrier.wait(timeout=10)
        try:
            return service.callback(state=state, code='test-only-code')['authorized']
        except ProviderError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: invoke(), range(2)))
    assert sorted(map(str, results)) == ['OAUTH_STATE_INVALID', 'True'] and len(calls) == 1


def test_oauth_api_no_secret_response_and_validation(x_context):
    from app.main import app
    from app.api.v1.x_oauth import get_x_oauth_service
    from fastapi.testclient import TestClient
    c = x_context; service, calls, _ = setup(c)
    app.dependency_overrides[get_x_oauth_service] = lambda: service
    try:
        with TestClient(app) as client:
            start = client.post(f'/api/v1/projects/{c.project}/providers/X_API/oauth/start')
            assert start.status_code == 200 and set(start.json()) == {'authorize_url', 'expires_in'}
            state = parse_qs(urlsplit(start.json()['authorize_url']).query)['state'][0]
            response = client.get('/api/v1/providers/X_API/oauth/callback', params={'state': state, 'code': 'test-only-code'})
            assert response.status_code == 200 and response.json() == {'provider_type': 'X_API', 'authorized': True}
            assert 'test-only-new-access' not in response.text and 'test-only-new-refresh' not in response.text
            response = client.get('/api/v1/providers/X_API/oauth/callback', params={'state': state, 'code': 'test-only-code'})
            assert response.status_code == 409 and response.json()['error']['code'] == 'OAUTH_STATE_INVALID'
            assert 'test-only-code' not in response.text and state not in response.text
            paths = client.get('/openapi.json').json()['paths']
            assert len(paths) >= 42 and not any(p.startswith('/api/v2') for p in paths)
    finally: app.dependency_overrides.pop(get_x_oauth_service, None)


@pytest.mark.parametrize('missing,expected', [('RUNTIME_SECRET_KEY', 'SECRET_STORE_UNAVAILABLE'),
    ('X_REFRESH_TOKEN', 'PROVIDER_NOT_CONFIGURED'), ('X_TOKEN_EXPIRES_AT', 'PROVIDER_NOT_CONFIGURED'),
    ('X_CLIENT_ID', 'PROVIDER_NOT_CONFIGURED')])
def test_live_read_prerequisites_fail_before_network(x_context, missing, expected):
    c = x_context; c.source.environ.pop(missing)
    _, calls, client = setup(c)
    manager = XCredentialManager(c.factory, c.resolver, client, enabled=lambda: True, now=lambda: OBS)
    with c.factory() as s:
        with pytest.raises(ProviderError, match=expected):
            manager.resolve_connection(s.get(ProviderConnection, c.provider))
    assert not calls


def test_real_refresh_opt_in_required_even_when_live_reads_enabled(x_context, monkeypatch):
    c = x_context; expired(c)
    monkeypatch.setenv('X_LIVE_REFRESH_SMOKE_ENABLED', 'false')
    _, calls, client = setup(c)
    manager = XCredentialManager(c.factory, c.resolver, client, enabled=lambda: True, now=lambda: OBS)
    with c.factory() as s:
        with pytest.raises(ProviderError, match='X_LIVE_REFRESH_DISABLED'):
            manager.resolve_connection(s.get(ProviderConnection, c.provider))
    assert not calls
