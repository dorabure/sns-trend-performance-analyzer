from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from types import SimpleNamespace
from uuid import UUID, uuid4
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select
from app.db.models import JobRun, JobSchedule, JobStep, Project, ProviderConnection
from app.jobs.runner import JobRunner
from app.schemas.job_operations import ScheduleCreate, ScheduleFields, SchedulePatch
from app.services.job_operations_service import OperationsFailure
from app.services.provider_service import ProviderService
from app.services.schedule_time import next_run

UTC = timezone.utc
NOW = datetime(2026, 10, 4, 0, 0, tzinfo=UTC)


def create(ops, enabled=False):
    return ops.service.create_schedule(ops.pid, ScheduleCreate(provider_connection_id=ops.provider,
        schedule_mode='INTERVAL', interval_seconds=60, enabled=enabled))


def due(ops):
    row = create(ops, True)
    with ops.factory() as s, s.begin():
        schedule = s.get(JobSchedule, row['id']); schedule.next_run_at = NOW-timedelta(seconds=600)
    return row['id']


@pytest.mark.parametrize('values', [
    {'schedule_mode':'INTERVAL'}, {'schedule_mode':'INTERVAL','interval_seconds':59},
    {'schedule_mode':'INTERVAL','interval_seconds':True},
    {'schedule_mode':'INTERVAL','interval_seconds':60,'daily_time':'12:00'},
    {'schedule_mode':'DAILY','daily_time':'12:00'},
    {'schedule_mode':'DAILY','daily_time':'12:00','timezone':'Invalid/Zone'},
    {'schedule_mode':'DAILY','daily_time':'12:00','timezone':'UTC','interval_seconds':60},
    {'schedule_mode':'DAILY','daily_time':'12:00+09:00','timezone':'Asia/Tokyo'},
])
def test_invalid_schedule_contract(values):
    with pytest.raises(ValidationError): ScheduleFields(**values)


@pytest.mark.parametrize('zone,time,expected', [('Asia/Tokyo','09:00','2026-10-05T00:00:00+00:00'),
    ('UTC','00:01','2026-10-04T00:01:00+00:00'), ('Asia/Tokyo','08:59','2026-10-04T23:59:00+00:00')])
def test_daily_utc_boundaries(zone,time,expected):
    assert next_run(ScheduleFields(schedule_mode='DAILY', daily_time=time, timezone=zone),NOW).isoformat()==expected


def test_dst_gap_and_fold():
    daily=ScheduleFields(schedule_mode='DAILY',daily_time='02:30',timezone='America/New_York')
    assert next_run(daily,datetime(2026,3,8,5,tzinfo=UTC))==datetime(2026,3,8,7,tzinfo=UTC)
    daily.daily_time=datetime.strptime('01:30','%H:%M').time()
    assert next_run(daily,datetime(2026,11,1,5,45,tzinfo=UTC))==datetime(2026,11,2,6,30,tzinfo=UTC)


def test_interval_missed_runs_collapse():
    interval=ScheduleFields(schedule_mode='INTERVAL',interval_seconds=60)
    assert next_run(interval,NOW)==NOW+timedelta(seconds=60)
    assert next_run(interval,NOW,NOW-timedelta(days=10000))==NOW+timedelta(seconds=60)


def test_disabled_crud_scope_and_schedule_identity(ops):
    row=create(ops);sid=row['id']
    assert not row['enabled'] and row['next_run_at'] is None
    with pytest.raises(OperationsFailure,match='Job operation'): create(ops)
    assert ops.service.list_schedules(ops.pid)['total']==1
    assert ops.service.list_schedules(ops.pid,provider_type='INSTAGRAM_API')['total']==0
    assert ops.service.list_schedules(ops.demo)['items']==[]
    with pytest.raises(OperationsFailure) as e:ops.service.get_schedule(ops.other,sid)
    assert e.value.status==404
    edited=ops.service.patch_schedule(ops.pid,sid,SchedulePatch(schedule_mode='DAILY',interval_seconds=None,daily_time='09:00',timezone='Asia/Tokyo'))
    assert edited['daily_time'].hour==9
    enabled=ops.service.set_enabled(ops.pid,sid,True)
    assert enabled['next_run_at'] is not None
    assert ops.service.set_enabled(ops.pid,sid,False)['next_run_at'] is None
    ops.service.delete_schedule(ops.pid,sid)
    assert ops.service.list_schedules(ops.pid)['total']==0


def test_run_now_preserves_schedule_and_history_delete(ops):
    sid=due(ops)
    before=ops.service.get_schedule(ops.pid,sid)['next_run_at']
    accepted=ops.service.run_now(ops.pid,sid); jid=accepted['job_run_id']
    assert accepted['status']=='PENDING' and accepted['trigger_type']=='MANUAL'
    assert ops.service.get_schedule(ops.pid,sid)['next_run_at']==before
    detail=ops.service.get_job(ops.pid,jid)
    assert detail['scheduled_for'] is None and len(detail['steps'])==4
    assert detail['enqueued_at'] is not None and ops.calls==[jid]
    ops.service.delete_schedule(ops.pid,sid)
    assert ops.service.get_job(ops.pid,jid)['job_schedule_id'] is None


@pytest.mark.parametrize('cause,code', [('gate','LIVE_MODE_DISABLED'),('disabled','PROVIDER_NOT_READY'),
    ('not_connected','PROVIDER_NOT_READY'),('inactive','PROJECT_INACTIVE')])
def test_execution_readiness(ops,cause,code):
    row=create(ops)
    if cause=='gate':ops.service.enabled=lambda:False
    else:
        with ops.factory() as s,s.begin():
            if cause=='disabled':s.get(ProviderConnection,ops.provider).enabled=False
            if cause=='not_connected':s.get(ProviderConnection,ops.provider).connection_status='NOT_CONFIGURED'
            if cause=='inactive':s.get(Project,ops.pid).is_active=False
    for action in (lambda:ops.service.sync(ops.pid,'X_API'),lambda:ops.service.run_now(ops.pid,row['id']),
                   lambda:ops.service.set_enabled(ops.pid,row['id'],True)):
        with pytest.raises(OperationsFailure) as err: action()
        assert err.value.code==code
    assert ops.service.list_jobs(ops.pid)['total']==0 and not ops.calls


def test_tick_gate_keeps_due_boundary(ops):
    sid=due(ops);before=ops.service.get_schedule(ops.pid,sid)['next_run_at']
    ops.service.enabled=lambda:False
    assert ops.service.tick(NOW)==0
    assert ops.service.get_schedule(ops.pid,sid)['next_run_at']==before


def test_tick_atomic_acceptance_and_active_advance(ops):
    sid=due(ops)
    assert ops.service.tick(NOW)==1
    row=ops.service.get_schedule(ops.pid,sid)
    assert row['next_run_at']==NOW+timedelta(seconds=60) and row['last_run_at']==NOW
    jid=row['last_job']['id']; detail=ops.service.get_job(ops.pid,jid)
    assert detail['trigger_type']=='SCHEDULED' and detail['scheduled_for']==NOW-timedelta(seconds=600)
    assert len(detail['steps'])==4
    assert ops.service.tick(NOW+timedelta(seconds=60))==0
    after=ops.service.get_schedule(ops.pid,sid)
    assert after['last_job_run_id']==jid and after['last_run_at']==NOW
    assert after['next_run_at']==NOW+timedelta(seconds=120)
    assert ops.service.list_jobs(ops.pid)['total']==1


def test_atomic_creation_failure_rolls_back_job_steps_schedule(ops,monkeypatch):
    sid=due(ops);before=ops.service.get_schedule(ops.pid,sid)
    original=ops.service.jobs.create_in_session
    def fail(*args,**kwargs):
        original(*args,**kwargs)
        raise RuntimeError('PRIVATE_DUMMY')
    monkeypatch.setattr(ops.service.jobs,'create_in_session',fail)
    with pytest.raises(Exception):ops.service.tick(NOW)
    after=ops.service.get_schedule(ops.pid,sid)
    assert after['next_run_at']==before['next_run_at'] and after['last_job_run_id'] is None
    assert ops.service.list_jobs(ops.pid)['total']==0 and not ops.calls


def test_two_ticks_skip_locked_and_manual_race(ops):
    sid=due(ops);barrier=Barrier(2)
    def tick():barrier.wait();return ops.service.tick(NOW)
    with ThreadPoolExecutor(max_workers=2) as pool:assert sum(pool.map(lambda _:tick(),range(2)))==1
    first=ops.service.list_jobs(ops.pid)['items'][0]['id'];ops.service.cancel(ops.pid,first)
    with ops.factory() as s,s.begin():s.get(JobSchedule,sid).next_run_at=NOW
    barrier=Barrier(2)
    def race(manual):
        barrier.wait()
        try:return ops.service.sync(ops.pid,'X_API') if manual else ops.service.tick(NOW)
        except OperationsFailure as error:return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(race,[False,True]))
    with ops.factory() as s:
        assert s.scalar(select(func.count()).select_from(JobRun).where(JobRun.project_id==ops.pid,JobRun.status.in_(['PENDING','RUNNING'])))==1


def test_dispatch_failure_reconciliation_and_duplicate_execution(ops):
    def unavailable(jid):raise RuntimeError('PRIVATE_BROKER_PASSWORD')
    ops.dispatcher.publisher=unavailable
    accepted=ops.service.sync(ops.pid,'X_API');jid=accepted['job_run_id']
    assert ops.service.get_job(ops.pid,jid)['enqueued_at'] is None
    ops.dispatcher.publisher=lambda id:ops.calls.append(id)
    assert ops.dispatcher.reconcile(now=NOW)==1
    assert ops.dispatcher.reconcile(now=NOW+timedelta(seconds=299))==0
    assert ops.dispatcher.reconcile(now=NOW+timedelta(seconds=300))==1
    assert ops.calls==[jid,jid]
    assert JobRunner(ops.service.jobs).execute(jid)=='FAILED'
    assert JobRunner(ops.service.jobs).execute(jid)=='NO_OP'
    assert ops.service.get_job(ops.pid,jid)['steps'][0]['attempt_count']==0
    assert ops.dispatcher.reconcile(now=NOW+timedelta(days=1))==0


def test_publish_then_missing_marker_recovers_same_uuid(ops):
    # Crash after broker acknowledgement and before marker commit: row still PENDING.
    accepted=ops.service.sync(ops.pid,'X_API');jid=accepted['job_run_id']
    with ops.factory() as s,s.begin():s.get(JobRun,jid).enqueued_at=None
    assert ops.dispatcher.reconcile()==1 and ops.calls==[jid,jid]
    assert ops.service.list_jobs(ops.pid)['total']==1


def test_pending_cancel_derived_progress_and_scope(ops):
    jid=ops.service.sync(ops.pid,'X_API')['job_run_id']
    providers=ProviderService(ops.factory)
    assert providers.detail(ops.pid,'X_API').sync_in_progress
    with pytest.raises(OperationsFailure) as e:ops.service.sync(ops.pid,'X_API')
    assert e.value.code=='JOB_ALREADY_RUNNING' and e.value.active_job_run_id==jid
    assert ops.service.list_jobs(ops.pid,status='PENDING',provider_type='X_API',trigger_type='MANUAL')['total']==1
    assert ops.service.list_jobs(ops.pid,status='FAILED')['total']==0
    with pytest.raises(Exception) as e:ops.service.get_job(ops.other,jid)
    assert e.value.status==404
    assert ops.service.cancel(ops.pid,jid)['status']=='CANCELED'
    assert all(s['status']=='CANCELED' for s in ops.service.get_job(ops.pid,jid)['steps'])
    assert not providers.detail(ops.pid,'X_API').sync_in_progress
    assert JobRunner(ops.service.jobs).execute(jid)=='NO_OP'
    with pytest.raises(OperationsFailure) as e:ops.service.cancel(ops.pid,jid)
    assert e.value.code=='JOB_NOT_CANCELABLE'
    jid=ops.service.sync(ops.pid,'X_API')['job_run_id'];ops.service.jobs.claim(jid)
    with pytest.raises(OperationsFailure) as e:ops.service.cancel(ops.pid,jid)
    assert e.value.code=='JOB_NOT_CANCELABLE'
    ops.service.jobs.fail_execution(jid,'JOB_HANDLER_NOT_IMPLEMENTED')


def test_api_contract_errors_paging_and_no_sensitive_metadata(ops):
    from app.main import app
    from app.api.v1.job_operations import get_operations_service
    app.dependency_overrides[get_operations_service]=lambda:ops.service
    try:
        with TestClient(app) as client:
            base=f'/api/v1/projects/{ops.pid}'
            body=dict(provider_connection_id=str(ops.provider),schedule_mode='INTERVAL',interval_seconds=60)
            response=client.post(base+'/schedules',json=body);assert response.status_code==201
            sid=response.json()['id']
            assert client.post(base+'/schedules',json=body).json()['error']['code']=='SCHEDULE_ALREADY_EXISTS'
            assert client.patch(base+'/schedules/'+sid,json={'enabled':True}).status_code==422
            assert client.patch(base+'/schedules/'+sid,json={'next_run_at':'PRIVATE_DUMMY'}).status_code==422
            accepted=client.post(base+'/schedules/'+sid+'/run-now');assert accepted.status_code==202
            jid=accepted.json()['job_run_id']
            conflict=client.post(base+'/providers/X_API/sync')
            assert conflict.status_code==409 and conflict.json()['error']['active_job_run_id']==jid
            assert client.get(base+'/jobs?page_size=101').status_code==422
            assert client.get(base+'/jobs?from=2026-01-01T00:00:00').status_code==422
            detail=client.get(base+'/jobs/'+jid);assert detail.status_code==200
            assert 'result_summary' not in detail.text and 'credentials' not in detail.text
            assert client.post(base+'/jobs/'+jid+'/cancel').status_code==200
            assert client.delete(base+'/schedules/'+sid).status_code==204
            assert client.get(base+'/jobs/'+jid).json()['job_schedule_id'] is None
    finally:app.dependency_overrides.pop(get_operations_service,None)


def test_worker_and_tick_gate_and_fixed_beat_entry(monkeypatch):
    from app.jobs.tasks import execute_job,scheduler_tick
    from app.jobs.celery_app import app
    monkeypatch.delenv('LIVE_MODE_ENABLED',raising=False)
    assert execute_job.run(str(uuid4()))=='LIVE_MODE_DISABLED'
    assert scheduler_tick.run()=='LIVE_MODE_DISABLED'
    assert len(app.conf.beat_schedule)==1
    assert app.conf.beat_schedule['scheduler-tick']['task']=='sns.scheduler_tick'
