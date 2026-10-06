import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
import httpx
import pytest
from app.providers.core import ProviderError
from app.providers.http_client import ProviderHTTPClient
from app.providers.instagram_oauth import (InstagramOAuthService, InstagramCredentialManager,
    InstagramTokenClient, SCOPES, token_payload)
from app.providers.credential_manager import CredentialManagerRouter
from app.db.models import ProviderConnection, Project
from app.core.oauth_log_filter import OAuthAccessFilter

NOW = datetime(2026, 10, 5, 1, tzinfo=timezone.utc)


def long_token(**changes):
    return dict({'token_type': 'bearer', 'access_token': 'test-only-ig-long', 'expires_in': 5184000}, **changes)


def setup(c, response=None):
    calls = []
    def mock(request):
        calls.append(request)
        if response is not None:
            return response if isinstance(response, httpx.Response) else httpx.Response(200, json=response)
        raw = {'data': [{'user_id': '111', 'access_token': 'test-only-ig-short',
                        'permissions': ','.join(SCOPES)}]} if request.method == 'POST' else long_token()
        return httpx.Response(200, json=raw)
    tokens = InstagramTokenClient(c.source, ProviderHTTPClient(transport=httpx.MockTransport(mock)))
    return InstagramOAuthService(c.factory, c.resolver, tokens, enabled=lambda: True, now=lambda: NOW), calls, tokens


def pending(c, service):
    query = parse_qs(urlsplit(service.start(c.project)['authorize_url']).query)
    state = query['state'][0]; name = service.pending_name(state)
    return state, name, json.loads(c.store.get_secret(name)), query


def test_oauth_encrypted_state_exact_scopes_no_pkce_and_long_lived(instagram_context, caplog):
    c = instagram_context; service, calls, _ = setup(c)
    state, name, record, query = pending(c, service)
    assert len(state) >= 43 and query['enable_fb_login'] == ['false']
    assert set(query['scope'][0].split(',')) == set(SCOPES)
    assert 'code_challenge' not in query and 'code_verifier' not in record
    assert state.encode() not in c.store.path(name).read_bytes()
    assert service.callback(state=state, code='test-only-ig-code') == {'provider_type': 'INSTAGRAM_API', 'authorized': True}
    assert len(calls) == 2 and calls[0].method == 'POST' and calls[1].method == 'GET'
    assert str(calls[0].url) == 'https://api.instagram.com/oauth/access_token'
    assert calls[1].url.host == 'graph.instagram.com' and calls[1].url.path == '/access_token'
    assert calls[0].headers['Content-Type'].startswith('multipart/form-data;')
    assert b'name="client_secret"' in calls[0].content and b'test-only-instagram-secret' in calls[0].content
    assert c.store.get_secret(name) is None
    credential = c.resolver.resolve('INSTAGRAM_API', c.ref)
    assert credential.access_token == 'test-only-ig-long' and credential.refresh_token is None
    assert credential.issued_at == NOW.isoformat() and 'test-only' not in repr(credential)
    with pytest.raises(ProviderError, match='OAUTH_STATE_INVALID'):
        service.callback(state=state, code='test-only-ig-code')
    assert len(calls) == 2 and not caplog.text


@pytest.mark.parametrize('scenario,expected', [('wrong', 'OAUTH_STATE_INVALID'), ('expired', 'OAUTH_STATE_EXPIRED'),
    ('redirect', 'OAUTH_STATE_INVALID'), ('project', 'OAUTH_PROVIDER_INVALID'), ('provider', 'OAUTH_PROVIDER_INVALID'),
    ('future', 'OAUTH_STATE_INVALID'), ('ttl', 'OAUTH_STATE_INVALID'), ('denied', 'OAUTH_STATE_INVALID'),
    ('missing_code', 'OAUTH_STATE_INVALID'), ('demo', 'OAUTH_PROVIDER_INVALID')])
def test_callback_invalid_no_network(instagram_context, monkeypatch, scenario, expected):
    c = instagram_context; service, calls, _ = setup(c)
    state, name, record, _ = pending(c, service)
    if scenario == 'wrong': state = 'x' * 43
    if scenario == 'expired':
        record['created_at'] = (NOW - timedelta(seconds=700)).isoformat()
        record['expires_at'] = (NOW - timedelta(seconds=100)).isoformat()
    if scenario == 'redirect': monkeypatch.setenv('INSTAGRAM_OAUTH_REDIRECT_URI', record['redirect_uri'].replace('callback.', 'other.'))
    if scenario == 'project': record['project_id'] = str(uuid4())
    if scenario == 'provider': record['provider_connection_id'] = str(uuid4())
    if scenario == 'future': record['created_at'] = (NOW + timedelta(seconds=1)).isoformat()
    if scenario == 'ttl': record['expires_at'] = (NOW + timedelta(days=1)).isoformat()
    if scenario == 'demo':
        with c.factory() as session, session.begin(): session.get(Project, c.project).data_mode = 'DEMO'
    c.store.set_secret(name, json.dumps(record))
    with pytest.raises(ProviderError, match=expected):
        service.callback(state=state, code=None if scenario == 'missing_code' else 'test-only-code',
                         error='access_denied' if scenario == 'denied' else None)
    assert not calls and c.store.get_secret(c.ref) is None


@pytest.mark.parametrize('state', [None, '', 'short', '../' * 20, 'é' * 50, 'x' * 129])
def test_bad_state(instagram_context, state):
    service, calls, _ = setup(instagram_context)
    with pytest.raises(ProviderError, match='OAUTH_STATE_INVALID'): service.callback(state=state, code='test-only')
    assert not calls


@pytest.mark.parametrize('live,oauth', [('false', 'false'), ('false', 'true'), ('true', 'false')])
def test_oauth_gate(instagram_context, monkeypatch, live, oauth):
    monkeypatch.setenv('LIVE_MODE_ENABLED', live); monkeypatch.setenv('INSTAGRAM_OAUTH_BOOTSTRAP_ENABLED', oauth)
    c = instagram_context
    with pytest.raises(ProviderError, match='OAUTH_DISABLED'): InstagramOAuthService(c.factory, c.resolver).start(c.project)


@pytest.mark.parametrize('response,expected', [(httpx.Response(400, json={'error_message': 'private'}), 'PROVIDER_AUTH_FAILED'),
    (httpx.Response(401), 'PROVIDER_AUTH_FAILED'), (httpx.Response(403), 'PROVIDER_PERMISSION_DENIED'),
    (httpx.Response(500), 'PROVIDER_SERVER_ERROR'), ({'data': []}, 'PROVIDER_RESPONSE_INVALID'),
    ({'data': [{'user_id': '111', 'access_token': 'test-only', 'permissions': SCOPES[0]}]}, 'OAUTH_SCOPE_INSUFFICIENT')])
def test_code_errors_single_use_keep_old_credential(instagram_context, response, expected, caplog):
    c = instagram_context; c.store.set_secret(c.ref, json.dumps(token_payload(long_token(), NOW)))
    before = c.store.path(c.ref).read_bytes(); service, calls, _ = setup(c, response)
    state, name, _, _ = pending(c, service)
    with pytest.raises(ProviderError, match=expected): service.callback(state=state, code='test-only-code')
    assert len(calls) == 1 and c.store.get_secret(name) is None
    assert c.store.path(c.ref).read_bytes() == before and not caplog.text


@pytest.mark.parametrize('operation', ['code', 'exchange', 'refresh'])
@pytest.mark.parametrize('failure', ['timeout', 'network', 'server'])
def test_lifecycle_requests_never_replay(operation, failure, caplog):
    calls = []
    def mock(request):
        calls.append(request)
        if failure == 'timeout': raise httpx.ReadTimeout('private query secret')
        if failure == 'network': raise httpx.ConnectError('private query secret')
        return httpx.Response(503, json={'error': {'message': 'private query secret'}})
    client = ProviderHTTPClient(transport=httpx.MockTransport(mock))
    fields = {'grant_type': 'authorization_code', 'client_id': '123', 'client_secret': 'test-only',
        'code': 'test-only', 'redirect_uri': 'https://example.invalid'} if operation == 'code' else (
        {'grant_type': 'ig_exchange_token', 'client_secret': 'test-only', 'access_token': 'test-only'} if operation == 'exchange'
        else {'grant_type': 'ig_refresh_token', 'access_token': 'test-only'})
    with pytest.raises(ProviderError) as caught: client.instagram_token(operation, fields)
    assert len(calls) == 1 and 'private' not in str(caught.value) and not caplog.text


def manager(c, tokens):
    return InstagramCredentialManager(c.factory, c.resolver, tokens, enabled=lambda: True, now=lambda: NOW)


@pytest.mark.parametrize('scenario,expected', [('not_due', None), ('due', None), ('expired', 'INSTAGRAM_REAUTH_REQUIRED'),
    ('young', 'INSTAGRAM_REFRESH_TOO_EARLY'), ('disabled', 'INSTAGRAM_LIVE_REFRESH_DISABLED'),
    ('missing_issued', 'PROVIDER_NOT_CONFIGURED'), ('future', 'PROVIDER_RESPONSE_INVALID')])
def test_refresh_eligibility_and_rotation(instagram_context, monkeypatch, scenario, expected):
    c = instagram_context; _, calls, tokens = setup(c)
    issued = NOW - timedelta(days=55); expires = NOW + timedelta(days=5)
    if scenario == 'not_due': issued, expires = NOW - timedelta(days=1), NOW + timedelta(days=59)
    if scenario == 'expired': issued, expires = NOW - timedelta(days=60), NOW
    if scenario == 'young': issued, expires = NOW - timedelta(hours=23), NOW + timedelta(days=2)
    if scenario == 'disabled': monkeypatch.setenv('INSTAGRAM_LIVE_REFRESH_SMOKE_ENABLED', 'false')
    if scenario == 'future': issued = NOW + timedelta(hours=1)
    payload = {'schema_version': 1, 'access_token': 'test-only-ig-old', 'expires_at': expires.isoformat(), 'issued_at': issued.isoformat()}
    if scenario == 'missing_issued': payload.pop('issued_at')
    c.store.set_secret(c.ref, json.dumps(payload)); before = c.store.path(c.ref).read_bytes()
    with c.factory() as session: row = session.get(ProviderConnection, c.provider)
    current = manager(c, tokens)
    if expected:
        with pytest.raises(ProviderError, match=expected): current.resolve_connection(row)
        assert not calls and c.store.path(c.ref).read_bytes() == before
    else:
        result = current.resolve_connection(row)
        assert len(calls) == (1 if scenario == 'due' else 0)
        assert result.access_token == ('test-only-ig-long' if scenario == 'due' else 'test-only-ig-old')
        assert result.refresh_token is None


def test_refresh_parallel_rows_share_logical_lock_and_reload(instagram_context):
    c = instagram_context; _, calls, tokens = setup(c)
    c.store.set_secret(c.ref, json.dumps(token_payload(long_token(access_token='test-only-old'), NOW - timedelta(days=55))))
    with c.factory() as session, session.begin():
        second = ProviderConnection(project_id=c.project, provider_type='INSTAGRAM_API', enabled=True, credential_ref=c.ref)
        # Schema has one connection per project/provider; use a second LIVE project.
        project = Project(name='Isolated shared IG reference', data_mode='LIVE'); session.add(project); session.flush()
        second.project_id = project.project_id; session.add(second); session.flush()
        second_project, second_id = project.project_id, second.id
    try:
        current = manager(c, tokens)
        def resolve(pid):
            with c.factory() as session: row = session.get(ProviderConnection, pid)
            return current.resolve_connection(row).access_token
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(resolve, [c.provider, second_id])) == ['test-only-ig-long'] * 2
        assert len(calls) == 1
    finally:
        from sqlalchemy import delete
        with c.factory() as session, session.begin(): session.execute(delete(Project).where(Project.project_id == second_project))


def test_refresh_failure_atomic_and_overlay_unknown(instagram_context):
    c = instagram_context; _, calls, tokens = setup(c, httpx.Response(500))
    c.store.set_secret(c.ref, json.dumps(token_payload(long_token(), NOW - timedelta(days=55))))
    before = c.store.path(c.ref).read_bytes()
    with c.factory() as session: row = session.get(ProviderConnection, c.provider)
    with pytest.raises(ProviderError, match='PROVIDER_SERVER_ERROR'): manager(c, tokens).resolve_connection(row)
    assert len(calls) == 1 and c.store.path(c.ref).read_bytes() == before
    raw = json.loads(c.store.get_secret(c.ref)); raw['unknown'] = 'private'; c.store.set_secret(c.ref, json.dumps(raw))
    with pytest.raises(ProviderError, match='SECRET_STORE_UNAVAILABLE'): c.resolver.resolve('INSTAGRAM_API', c.ref)


def test_router_selects_provider_and_session_without_x_change():
    calls = []
    class Manager:
        def __init__(self, kind): self.kind = kind
        def resolve_connection(self, provider, session=None): calls.append((self.kind, session)); return self.kind
    router = CredentialManagerRouter(None, x_manager=Manager('X'), instagram_manager=Manager('IG'))
    session = object()
    assert router.resolve_connection(SimpleNamespace(provider_type='X_API'), session) == 'X'
    assert router.resolve_connection(SimpleNamespace(provider_type='INSTAGRAM_API'), session) == 'IG'
    assert calls == [('X', session), ('IG', session)]
    with pytest.raises(ProviderError, match='PROVIDER_NOT_IMPLEMENTED'): router.resolve_connection(SimpleNamespace(provider_type='OTHER'))


def test_instagram_callback_access_query_scrubbed():
    record = logging.LogRecord('uvicorn.access', logging.INFO, '', 0, '%s - "%s %s HTTP/%s" %d',
        ('local', 'GET', '/api/v1/providers/INSTAGRAM_API/oauth/callback?state=private&code=private', '1.1', 200), None)
    OAuthAccessFilter().filter(record)
    assert '?' not in record.args[2] and 'private' not in record.getMessage()


@pytest.mark.parametrize('age,expected_calls', [(86399, 0), (86400, 1)])
def test_explicit_refresh_respects_real_minimum_age(instagram_context, age, expected_calls):
    c = instagram_context; _, calls, tokens = setup(c)
    c.store.set_secret(c.ref, json.dumps(token_payload(long_token(), NOW - timedelta(seconds=age))))
    with c.factory() as session: row = session.get(ProviderConnection, c.provider)
    current = manager(c, tokens)
    if expected_calls:
        assert current.refresh_connection(row).issued_at == NOW.isoformat()
    else:
        with pytest.raises(ProviderError, match='INSTAGRAM_REFRESH_TOO_EARLY'): current.refresh_connection(row)
    assert len(calls) == expected_calls
