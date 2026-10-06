import json
from concurrent.futures import ThreadPoolExecutor
import httpx
import pytest
from cryptography.fernet import Fernet
from app.providers.core import ProviderCredential, ProviderError, ProviderCapability, ProviderRegistry, checked_capabilities, safe_raw
from app.providers.secret_store import EnvOrFileSecretSource, EncryptedFileSecretStore, ProviderCredentialResolver
from app.providers.http_client import ProviderHTTPClient


def store(path, key=None):
    return EncryptedFileSecretStore(path, EnvOrFileSecretSource({'RUNTIME_SECRET_KEY': key or Fernet.generate_key().decode()}))


def test_persistence_atomic_permissions_and_delete(tmp_path):
    key = Fernet.generate_key().decode()
    current = store(tmp_path / 'cipher', key)
    current.set_secret('X_PRIMARY', 'test-only-value')
    paths = list((tmp_path / 'cipher').iterdir())
    assert len(paths) == 1 and paths[0].suffix == '.enc'
    assert b'test-only-value' not in paths[0].read_bytes()
    assert bool(store(tmp_path / 'cipher', key).get_secret('X_PRIMARY'))
    assert (paths[0].stat().st_mode & 0o777) == 0o600
    current.delete_secret('X_PRIMARY')
    current.delete_secret('X_PRIMARY')
    assert current.get_secret('X_PRIMARY') is None


def test_wrong_key_and_tamper_fail_closed(tmp_path):
    current = store(tmp_path)
    current.set_secret('REFERENCE', 'test-only-value')
    with pytest.raises(ProviderError, match='SECRET_STORE_UNAVAILABLE'):
        store(tmp_path).get_secret('REFERENCE')
    path = current.path('REFERENCE')
    path.write_bytes(path.read_bytes()[:-1] + b'!')
    with pytest.raises(ProviderError, match='SECRET_STORE_UNAVAILABLE'):
        current.get_secret('REFERENCE')


def test_missing_key_and_colocated_key(tmp_path):
    current = EncryptedFileSecretStore(tmp_path, EnvOrFileSecretSource({}))
    for operation in [lambda: current.get_secret('x'), lambda: current.set_secret('x', 'value'), lambda: current.delete_secret('x')]:
        with pytest.raises(ProviderError, match='SECRET_STORE_UNAVAILABLE'):
            operation()
    keyfile = tmp_path / 'key'
    keyfile.write_bytes(Fernet.generate_key())
    current = EncryptedFileSecretStore(tmp_path, EnvOrFileSecretSource({'RUNTIME_SECRET_KEY_FILE': str(keyfile)}))
    with pytest.raises(ProviderError, match='SECRET_STORE_UNAVAILABLE'):
        current.get_secret('x')


def test_env_file_bootstrap_overlay_and_repr(tmp_path):
    keyfile = tmp_path / 'outside-key'
    keyfile.write_bytes(Fernet.generate_key())
    bootstrap = tmp_path / 'outside-bootstrap'
    bootstrap.write_text('test-bootstrap\n')
    source = EnvOrFileSecretSource({'RUNTIME_SECRET_KEY_FILE': str(keyfile), 'X_USER_ACCESS_TOKEN_FILE': str(bootstrap), 'X_CLIENT_SECRET': 'test-client'})
    current = EncryptedFileSecretStore(tmp_path / 'cipher', source)
    resolver = ProviderCredentialResolver(source, current)
    assert resolver.configured('X_API')
    credential = resolver.resolve('X_API')
    assert 'test-' not in repr(credential)
    current.set_secret('X_PRIMARY', json.dumps({'schema_version': 1, 'access_token': 'test-overlay', 'refresh_token': 'test-refresh', 'expires_at': '2026-10-05T00:00:00Z'}))
    credential = resolver.resolve('X_API')
    assert bool(credential.access_token == 'test-overlay')
    assert bool(credential.client_secret)
    assert credential.expires_at is not None
    current.delete_secret('X_PRIMARY')
    assert bool(resolver.resolve('X_API').access_token == 'test-bootstrap')


def test_concurrent_atomic_replace(tmp_path):
    current = store(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: current.set_secret('SAME', str(i)), range(20)))
    assert current.get_secret('SAME') in {str(i) for i in range(20)}
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize('values', [['UNKNOWN'], ['OWN_POSTS', 'OWN_POSTS'], ['access_token'], 'OWN_POSTS', [None]])
def test_capabilities_reject_unknown_duplicate_secrets(values):
    with pytest.raises(ValueError):
        checked_capabilities(values)


def test_registry_empty_safe_raw_and_credential_error():
    with pytest.raises(ProviderError, match='PROVIDER_NOT_IMPLEMENTED'):
        ProviderRegistry({}).get('X_API')
    assert set(safe_raw({'id': '1', 'access_token': 'test-only-value', 'unknown': 'ignored'})) == {'id'}
    assert len(ProviderCapability) == 6
    assert 'test-only-value' not in repr(ProviderCredential('test-only-value'))


@pytest.mark.parametrize('status,code,retry', [(400,'PROVIDER_BAD_REQUEST',False),(401,'PROVIDER_AUTH_FAILED',False),(403,'PROVIDER_PERMISSION_DENIED',False),(429,'PROVIDER_RATE_LIMITED',True),(500,'PROVIDER_SERVER_ERROR',True),(503,'PROVIDER_SERVER_ERROR',True),(302,'PROVIDER_BAD_REQUEST',False)])
def test_http_error_mapping_retry_and_safe_output(status, code, retry, caplog):
    calls, sleeps, beats = [], [], []
    def transport(request):
        calls.append(request)
        assert request.url.scheme == 'https'
        assert request.extensions['timeout']['connect'] == 5
        return httpx.Response(status, text='test-only-sensitive-body')
    client = ProviderHTTPClient(transport=httpx.MockTransport(transport), sleep=sleeps.append, jitter=lambda: 0)
    with pytest.raises(ProviderError) as failure:
        client.get_json('https://provider.invalid/data', ProviderCredential('test-only-value'), heartbeat=lambda: beats.append(1))
    assert failure.value.code == code
    assert len(calls) == (3 if retry else 1)
    assert len(beats) == len(calls)*2
    assert sleeps == ([1,2] if retry else [])
    assert 'test-only-' not in str(failure.value) + repr(failure.value) + caplog.text
    assert not caplog.text


@pytest.mark.parametrize('after,expected', [('2',2), ('999999',None), ('bad',1)])
def test_retry_after_bounded(after, expected):
    calls, sleeps = [], []
    def transport(request):
        calls.append(1)
        return httpx.Response(429, headers={'Retry-After': after}) if len(calls) == 1 else httpx.Response(200, json={'ok': True})
    client = ProviderHTTPClient(transport=httpx.MockTransport(transport), sleep=sleeps.append, jitter=lambda: 0)
    if expected is None:
        with pytest.raises(ProviderError, match='PROVIDER_RATE_LIMITED'):
            client.get_json('https://provider.invalid/data', ProviderCredential('dummy'))
        assert len(calls) == 1 and not sleeps
    else:
        assert client.get_json('https://provider.invalid/data', ProviderCredential('dummy'))['ok']
        assert sleeps == [expected]


@pytest.mark.parametrize('error,code', [(httpx.ConnectError,'PROVIDER_NETWORK_ERROR'), (httpx.ReadTimeout,'PROVIDER_TIMEOUT')])
def test_network_timeout_max_attempts(error, code):
    calls = []
    def transport(request):
        calls.append(1)
        raise error('test-only-value')
    client = ProviderHTTPClient(transport=httpx.MockTransport(transport), sleep=lambda _: None)
    with pytest.raises(ProviderError, match=code):
        client.get_json('https://provider.invalid/data', ProviderCredential('dummy'))
    assert len(calls) == 3


@pytest.mark.parametrize('url,params', [('http://provider.invalid/data',None), ('https://user:password@provider.invalid/data',None), ('https://provider.invalid/data?token=value',None), ('https://provider.invalid/data',{'access_token':'dummy'})])
def test_url_credentials_query_and_tls_rejected(url, params):
    client = ProviderHTTPClient(transport=httpx.MockTransport(lambda _: pytest.fail('must not request')))
    with pytest.raises(ProviderError, match='PROVIDER_BAD_REQUEST'):
        client.get_json(url, ProviderCredential('dummy'), params=params)


def test_invalid_json_no_retry():
    calls = []
    client = ProviderHTTPClient(transport=httpx.MockTransport(lambda _: (calls.append(1) or httpx.Response(200, text='not json'))))
    with pytest.raises(ProviderError, match='PROVIDER_RESPONSE_INVALID'):
        client.get_json('https://provider.invalid/data', ProviderCredential('dummy'))
    assert len(calls) == 1


@pytest.mark.parametrize('value', ['0','-1','inf','nan','999999','bad'])
def test_timeout_config_rejects_unbounded(monkeypatch, value):
    monkeypatch.setenv('PROVIDER_READ_TIMEOUT_SECONDS', value)
    with pytest.raises(ProviderError, match='PROVIDER_BAD_REQUEST'):
        ProviderHTTPClient()


@pytest.mark.parametrize('name', ['', '../escape', '/absolute', 'lowercase', 'A/B', None, 'X'*129])
def test_invalid_secret_names_rejected(tmp_path, name):
    current = store(tmp_path)
    with pytest.raises(ProviderError, match='SECRET_STORE_UNAVAILABLE'):
        current.set_secret(name, 'test-only-value')
    assert not list(tmp_path.iterdir())


def test_whole_attempt_deadline_cancels_transport():
    import asyncio
    calls, canceled = [], []
    async def slow(request):
        calls.append(1)
        try:
            await asyncio.sleep(1)
        finally:
            canceled.append(1)
        return httpx.Response(200,json={'ok': True})
    client = ProviderHTTPClient(transport=httpx.MockTransport(slow),request_timeout=0.01,sleep=lambda _:None)
    with pytest.raises(ProviderError, match='PROVIDER_TIMEOUT'):
        client.get_json('https://provider.invalid/data',ProviderCredential('dummy'))
    assert len(calls)==3 and len(canceled)==3
