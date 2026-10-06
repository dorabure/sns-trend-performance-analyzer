from types import SimpleNamespace
import pytest
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker
from app.db.models import Project, ProviderConnection
from app.services.job_service import JobService


@pytest.fixture
def job_context(postgres_engine):
    factory = sessionmaker(postgres_engine, expire_on_commit=False)
    with factory() as s, s.begin():
        project = Project(name='Isolated job project', data_mode='LIVE')
        s.add(project); s.flush()
        providers = [ProviderConnection(project_id=project.project_id, provider_type=t) for t in ('X_API', 'INSTAGRAM_API')]
        s.add_all(providers); s.flush()
        pid, provider, other = project.project_id, providers[0].id, providers[1].id
    try:
        yield SimpleNamespace(factory=factory, project=pid, provider=provider, other=other, service=JobService(factory))
    finally:
        with factory() as s, s.begin():
            s.execute(delete(Project).where(Project.project_id == pid))


@pytest.fixture
def job(job_context):
    return job_context.service.create(job_context.project, 'LIVE', job_context.provider)
