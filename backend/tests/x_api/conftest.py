import pytest


@pytest.fixture(autouse=True)
def prohibit_real_http(monkeypatch):
    monkeypatch.setenv('X_OAUTH_CLIENT_TYPE', 'PUBLIC')
    monkeypatch.setenv('X_LIVE_REFRESH_SMOKE_ENABLED', 'true')
    import httpx
    def deny(*args, **kwargs):
        raise AssertionError('Real HTTP is forbidden in X integration tests')
    async def async_deny(*args, **kwargs):
        raise AssertionError('Real HTTP is forbidden in X integration tests')
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', deny)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', async_deny)


@pytest.fixture
def x_context(postgres_engine, tmp_path):
    from uuid import uuid4
    from types import SimpleNamespace
    from cryptography.fernet import Fernet
    from sqlalchemy import delete
    from sqlalchemy.orm import sessionmaker
    from app.db.models import Project, ProjectPlatform, ProviderConnection
    from app.providers.secret_store import EnvOrFileSecretSource, EncryptedFileSecretStore, ProviderCredentialResolver
    from app.services.job_service import JobService
    factory = sessionmaker(postgres_engine, expire_on_commit=False)
    with factory() as s, s.begin():
        project = Project(name='Isolated Phase6 X', data_mode='LIVE')
        s.add(project); s.flush()
        s.add(ProjectPlatform(project_id=project.project_id, platform='X'))
        provider = ProviderConnection(project_id=project.project_id, provider_type='X_API', enabled=True,
            credential_ref='X_TEST_' + uuid4().hex.upper())
        s.add(provider); s.flush()
        pid, provider_id, ref = project.project_id, provider.id, provider.credential_ref
    source = EnvOrFileSecretSource({'RUNTIME_SECRET_KEY': Fernet.generate_key().decode(),
        'X_USER_ACCESS_TOKEN': 'test-only-access', 'X_REFRESH_TOKEN': 'test-only-refresh',
        'X_CLIENT_ID': 'test-only-client', 'X_CLIENT_SECRET': 'test-only-client-secret',
        'X_TOKEN_EXPIRES_AT': '2099-01-01T00:00:00+00:00'})
    store = EncryptedFileSecretStore(tmp_path / 'runtime', source)
    resolver = ProviderCredentialResolver(source, store)
    c = SimpleNamespace(factory=factory, project=pid, provider=provider_id, ref=ref,
        store=store, source=source, resolver=resolver, jobs=JobService(factory))
    try:
        yield c
    finally:
        with factory() as s, s.begin():
            s.execute(delete(Project).where(Project.project_id == pid))
