from types import SimpleNamespace
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker
from app.db.models import Project, ProjectPlatform, ProviderConnection
from app.providers.core import ProviderRegistry
from app.providers.secret_store import EnvOrFileSecretSource, EncryptedFileSecretStore, ProviderCredentialResolver
from app.services.job_service import JobService
from app.services.provider_sync_handler import ProviderSyncHandler
from tests.provider_core.mocks import MockXProvider, MockInstagramProvider


@pytest.fixture(autouse=True)
def forbid_real_provider_http(monkeypatch):
    import httpx
    def blocked(*args, **kwargs):
        raise AssertionError('Real provider HTTP is forbidden in Phase 5 tests')
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', blocked)
    async def async_blocked(*args, **kwargs):
        raise AssertionError('Real provider HTTP is forbidden in Phase 5 tests')
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', async_blocked)


@pytest.fixture(params=['X_API', 'INSTAGRAM_API'])
def live_context(postgres_engine, tmp_path, request):
    factory = sessionmaker(postgres_engine, expire_on_commit=False)
    kind = request.param
    platform = 'X' if kind == 'X_API' else 'INSTAGRAM'
    with factory() as s, s.begin():
        project = Project(name='Isolated provider core', data_mode='LIVE')
        s.add(project); s.flush()
        s.add(ProjectPlatform(project_id=project.project_id, platform=platform))
        provider = ProviderConnection(project_id=project.project_id, provider_type=kind, enabled=True)
        s.add(provider); s.flush()
        pid, provider_id = project.project_id, provider.id
    prefix = 'X' if kind == 'X_API' else 'INSTAGRAM'
    source = EnvOrFileSecretSource({'RUNTIME_SECRET_KEY': Fernet.generate_key().decode(), prefix + '_USER_ACCESS_TOKEN': 'test-only-credential'})
    store = EncryptedFileSecretStore(tmp_path / 'cipher', source)
    resolver = ProviderCredentialResolver(source, store)
    remote = MockXProvider() if kind == 'X_API' else MockInstagramProvider()
    registry = ProviderRegistry({kind: lambda: (remote, remote.normalizer())})
    jobs = JobService(factory)
    handler = ProviderSyncHandler(factory, registry=registry, resolver=resolver, enabled=lambda: True)
    context = SimpleNamespace(factory=factory, project=pid, provider=provider_id, kind=kind,
        remote=remote, registry=registry, resolver=resolver, jobs=jobs, handler=handler)
    try:
        yield context
    finally:
        with factory() as s, s.begin():
            s.execute(delete(Project).where(Project.project_id == pid))
