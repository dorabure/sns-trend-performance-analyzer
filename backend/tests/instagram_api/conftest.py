import pytest


@pytest.fixture(autouse=True)
def instagram_config(monkeypatch):
    monkeypatch.setenv('INSTAGRAM_GRAPH_API_VERSION', 'v26.0')
    monkeypatch.setenv('INSTAGRAM_OAUTH_REDIRECT_URI',
        'https://callback.example.invalid/api/v1/providers/INSTAGRAM_API/oauth/callback')
    monkeypatch.setenv('INSTAGRAM_LIVE_REFRESH_SMOKE_ENABLED', 'true')


@pytest.fixture
def instagram_context(postgres_engine, tmp_path):
    from uuid import uuid4
    from types import SimpleNamespace
    from cryptography.fernet import Fernet
    from sqlalchemy import delete
    from sqlalchemy.orm import sessionmaker
    from app.db.models import Project, ProjectPlatform, ProviderConnection
    from app.providers.secret_store import EnvOrFileSecretSource, EncryptedFileSecretStore, ProviderCredentialResolver
    from app.services.job_service import JobService
    factory = sessionmaker(postgres_engine, expire_on_commit=False)
    with factory() as session, session.begin():
        project = Project(name='Isolated Phase7 Instagram', data_mode='LIVE')
        session.add(project); session.flush()
        session.add(ProjectPlatform(project_id=project.project_id, platform='INSTAGRAM'))
        provider = ProviderConnection(project_id=project.project_id, provider_type='INSTAGRAM_API',
            enabled=True, credential_ref='INSTAGRAM_TEST_' + uuid4().hex.upper())
        session.add(provider); session.flush()
        pid, provider_id, ref = project.project_id, provider.id, provider.credential_ref
    source = EnvOrFileSecretSource({'RUNTIME_SECRET_KEY': Fernet.generate_key().decode(),
        'INSTAGRAM_CLIENT_ID': '123456', 'INSTAGRAM_CLIENT_SECRET': 'test-only-instagram-secret'})
    store = EncryptedFileSecretStore(tmp_path / 'runtime', source)
    resolver = ProviderCredentialResolver(source, store)
    try:
        yield SimpleNamespace(factory=factory, project=pid, provider=provider_id, ref=ref,
            store=store, source=source, resolver=resolver, jobs=JobService(factory))
    finally:
        with factory() as session, session.begin():
            session.execute(delete(Project).where(Project.project_id == pid))
