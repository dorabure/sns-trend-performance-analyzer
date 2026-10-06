"""Opt-in Docker/Redis outage probe. Never operates on the application database.

Run inside a backend container: init -> accept (Redis down) -> reconcile
-> check (dedicated worker) -> duplicate -> check -> cleanup.
"""
import json
import sys
from pathlib import Path
from uuid import uuid4, UUID
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.core.config import get_settings
from app.db.models import Project, ProviderConnection, JobRun
from app.jobs.celery_app import app
from app.services.job_dispatch_service import JobDispatchService
from app.services.job_operations_service import JobOperationsService
from tests.postgres_support import migrate, validate_test_database

STATE = Path('/tmp/phase4_runtime_probe.json')
url = get_settings().database_url
action = sys.argv[1]
if action == 'init':
    assert not STATE.exists(), 'Probe already exists'
    name = 'sns_phase2_test_' + uuid4().hex
    validate_test_database(name, url.database)
    admin = create_engine(url.set(database='postgres'), isolation_level='AUTOCOMMIT')
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(url.set(database=name))
    migrate(engine, 'upgrade', 'head')
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as s, s.begin():
        project = Project(name='Disposable Redis probe', data_mode='LIVE')
        s.add(project); s.flush()
        provider = ProviderConnection(project_id=project.project_id, provider_type='X_API', enabled=True, connection_status='CONNECTED', capabilities=['ACCOUNT_PROFILE', 'OWN_POSTS', 'OWN_METRICS'])
        s.add(provider); s.flush()
        state = dict(database=name, project=str(project.project_id), provider=str(provider.id), queue='phase4_probe_' + uuid4().hex)
    STATE.write_text(json.dumps(state))
else:
    state = json.loads(STATE.read_text())
    validate_test_database(state['database'], url.database)
    engine = create_engine(url.set(database=state['database']))
    factory = sessionmaker(engine, expire_on_commit=False)
    def publish(jid):
        return app.send_task('sns.execute_job', args=[str(jid)], queue=state['queue'], argsrepr='(<job_run_id>,)', kwargsrepr='{}')
    dispatcher = JobDispatchService(factory, publisher=publish, enabled=lambda: True)
    service = JobOperationsService(factory, enabled=lambda: True, dispatcher=dispatcher)
    if action == 'accept':
        result = service.sync(UUID(state['project']), 'X_API')
        state['job'] = str(result['job_run_id'])
        job = service.get_job(UUID(state['project']), UUID(state['job']))
        assert job['status'] == 'PENDING' and job['enqueued_at'] is None
        STATE.write_text(json.dumps(state))
    elif action == 'reconcile':
        assert dispatcher.reconcile() == 1
        assert service.get_job(UUID(state['project']), UUID(state['job']))['enqueued_at'] is not None
    elif action == 'duplicate':
        with factory() as s:
            job = s.get(JobRun, UUID(state['job']))
            assert job.status == 'FAILED'
            state['started'] = job.started_at.isoformat()
            state['finished'] = job.finished_at.isoformat()
        STATE.write_text(json.dumps(state)); publish(state['job'])
    elif action == 'check':
        with factory() as s:
            job = s.get(JobRun, UUID(state['job']))
            assert job.status == 'FAILED' and job.error_code == 'X_LIVE_SMOKE_DISABLED'
            assert s.scalar(text('SELECT count(*) FROM job_runs')) == 1
            assert s.scalar(text('SELECT count(*) FROM job_steps')) == 4
            if 'started' in state:
                assert (job.started_at.isoformat(),job.finished_at.isoformat()) == (state['started'],state['finished'])
    elif action == 'cleanup':
        engine.dispose()
        admin = create_engine(url.set(database='postgres'), isolation_level='AUTOCOMMIT')
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE "{state["database"]}" WITH (FORCE)'))
        STATE.unlink()
    else:
        raise ValueError('Unsupported probe action')
print(json.dumps(dict(action=action, status='PASS', **state)))
