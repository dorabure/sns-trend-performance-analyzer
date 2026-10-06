from types import SimpleNamespace
import pytest
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker
from app.db.models import Project, ProviderConnection
from app.services.job_operations_service import JobOperationsService
from app.services.job_dispatch_service import JobDispatchService


@pytest.fixture
def ops(postgres_engine):
    factory = sessionmaker(postgres_engine, expire_on_commit=False)
    calls = []
    dispatcher = JobDispatchService(factory, publisher=lambda jid: calls.append(jid), enabled=lambda: True)
    service = JobOperationsService(factory, enabled=lambda: True, dispatcher=dispatcher)
    with factory() as s, s.begin():
        project = Project(name='Scheduler fixture', data_mode='LIVE')
        other = Project(name='Other LIVE fixture', data_mode='LIVE')
        demo = Project(name='Demo fixture', data_mode='DEMO')
        s.add_all([project, other, demo]); s.flush()
        providers = [ProviderConnection(project_id=project.project_id, provider_type=t, enabled=True,
            connection_status='CONNECTED', capabilities=['ACCOUNT_PROFILE', 'OWN_POSTS', 'OWN_METRICS'] if t == 'X_API' else ['ACCOUNT_PROFILE']) for t in ('X_API', 'INSTAGRAM_API')]
        s.add_all(providers); s.flush()
        context = SimpleNamespace(factory=factory, service=service, dispatcher=dispatcher, calls=calls,
            pid=project.project_id, other=other.project_id, demo=demo.project_id, provider=providers[0].id,
            second=providers[1].id)
    try:
        yield context
    finally:
        with factory() as s, s.begin():
            s.execute(delete(Project).where(Project.project_id.in_([context.pid, context.other, context.demo])))
