from uuid import uuid4
import pytest
from celery.exceptions import Reject
from app.jobs.celery_app import app
from app.jobs.tasks import execute_job,infrastructure_ping
from app.jobs.dispatch import dispatch_job
from app.services.job_service import JobFailure


def test_at_least_once_config():
    c=app.conf
    assert c.broker_url.startswith('redis://')
    assert c.task_serializer=='json' and c.accept_content==['json']
    assert c.task_acks_late and c.task_reject_on_worker_lost
    assert c.worker_prefetch_multiplier==1 and c.task_ignore_result and c.result_backend is None
    assert c.worker_cancel_long_running_tasks_on_connection_loss
    assert not c.task_send_sent_event and not c.worker_send_task_events


def test_ping_no_business_database():
    assert infrastructure_ping.run()=='PONG'


def test_task_db_failure_fixed_message(monkeypatch,caplog):
    monkeypatch.setenv('LIVE_MODE_ENABLED','true')
    def unavailable(*args):raise RuntimeError('Bearer PRIVATE_DUMMY SQL')
    monkeypatch.setattr('app.jobs.tasks.JobRunner.execute',unavailable)
    with pytest.raises(Reject) as err:execute_job.run(str(uuid4()))
    assert err.value.requeue and str(err.value.reason)=='JOB_STORAGE_UNAVAILABLE'
    assert 'PRIVATE_DUMMY' not in caplog.text


def test_task_unknown_job_and_invalid_id(monkeypatch):
    monkeypatch.setenv('LIVE_MODE_ENABLED','true')
    def missing(*args):raise JobFailure('JOB_NOT_FOUND')
    monkeypatch.setattr('app.jobs.tasks.JobRunner.execute',missing)
    assert execute_job.run(str(uuid4()))=='JOB_NOT_FOUND'
    assert execute_job.run('not a uuid')=='INVALID_JOB_ID'


def test_dispatch_only_uuid_and_broker_failure(monkeypatch):
    calls=[]
    monkeypatch.setattr(app,'send_task',lambda name,**kwargs:calls.append((name,kwargs)))
    identifier=uuid4();dispatch_job(identifier)
    assert calls[0][0]=='sns.execute_job' and calls[0][1]['args']==[str(identifier)]
    def fail(*args,**kwargs):raise RuntimeError('Bearer PRIVATE_DUMMY')
    monkeypatch.setattr(app,'send_task',fail)
    with pytest.raises(JobFailure,match='JOB_DISPATCH_UNAVAILABLE') as err:dispatch_job(identifier)
    assert 'PRIVATE_DUMMY' not in str(err.value)
