from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import uuid4
import pytest
from sqlalchemy import delete, select, func, event
from app.db.models import JobRun,JobStep,Project,ProviderConnection
from app.db.models.job import PIPELINE,TERMINAL
from app.services.job_service import JobService,JobFailure
from app.repositories.job_repository import JobRepository
from app.jobs.runner import JobRunner


def test_create_defaults_and_duplicate(job_context,job):
    c=job_context
    with c.factory() as s:
        row=s.get(JobRun,job)
        assert row.status=='PENDING' and row.result_summary=={}
        steps=c.service.repository.steps(s,job)
        assert [(x.step_type,x.sequence_no,x.status) for x in steps]==[(k,i,'PENDING') for i,k in enumerate(PIPELINE,1)]
    with pytest.raises(JobFailure) as err:c.service.create(c.project,'LIVE',c.provider)
    assert err.value.code=='JOB_ALREADY_RUNNING' and err.value.active_job_run_id==job
    with c.factory() as s:assert s.scalar(select(func.count()).select_from(JobRun).where(JobRun.project_id==c.project))==1


@pytest.mark.parametrize('case,code',[
    ('missing','PROJECT_NOT_FOUND'),('inactive','PROJECT_INACTIVE'),('mode','PROJECT_MODE_MISMATCH'),
    ('demo','INVALID_JOB_SCOPE'),('null','INVALID_JOB_SCOPE'),('type','INVALID_JOB_SCOPE'),
    ('provider_missing','PROVIDER_NOT_FOUND'),('provider_mismatch','PROVIDER_PROJECT_MISMATCH')])
def test_scope_validation(job_context,case,code):
    c=job_context; pid,mode,provider,kind=c.project,'LIVE',c.provider,'PROVIDER_SYNC'
    extra=None
    if case=='missing':pid=uuid4()
    if case=='inactive':
        with c.factory() as s,s.begin():s.get(Project,pid).is_active=False
    if case=='mode':mode='DEMO'
    if case=='demo':
        with c.factory() as s,s.begin():s.get(Project,pid).data_mode='DEMO'
        mode='DEMO'
    if case=='null':provider=None
    if case=='type':kind='ANALYTICS_REFRESH'
    if case=='provider_missing':provider=uuid4()
    if case=='provider_mismatch':
        with c.factory() as s,s.begin():
            p=Project(name='Other',data_mode='LIVE');s.add(p);s.flush();extra=p.project_id
            pc=ProviderConnection(project_id=p.project_id,provider_type='X_API');s.add(pc);s.flush();provider=pc.id
    try:
        with pytest.raises(JobFailure) as err:c.service.create(pid,mode,provider,kind)
        assert err.value.code==code
    finally:
        if extra:
            with c.factory() as s,s.begin():s.execute(delete(Project).where(Project.project_id==extra))


def test_atomic_step_failure_rollback(job_context):
    def fail(mapper,connection,target):raise RuntimeError('PRIVATE_DUMMY SQL')
    event.listen(JobStep,'before_insert',fail)
    try:
        with pytest.raises(JobFailure,match='JOB_STORAGE_ERROR'):
            job_context.service.create(job_context.project,'LIVE',job_context.provider)
    finally:event.remove(JobStep,'before_insert',fail)
    with job_context.factory() as s:
        assert s.scalar(select(func.count()).select_from(JobRun).where(JobRun.project_id==job_context.project))==0


def test_concurrent_prechecks_db_is_final_guard(job_context):
    barrier=Barrier(2)
    class RacingRepository(JobRepository):
        def active(self,*args,**kwargs):
            result=super().active(*args,**kwargs)
            if result is None:barrier.wait(timeout=10)
            return result
    service=JobService(job_context.factory,RacingRepository())
    def create():
        try:return ('created',service.create(job_context.project,'LIVE',job_context.provider))
        except JobFailure as e:return (e.code,e.active_job_run_id)
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:create(),range(2)))
    assert sorted(x[0] for x in results)==['JOB_ALREADY_RUNNING','created']
    assert results[0][1]==results[1][1]
    with job_context.factory() as s:
        assert s.scalar(select(func.count()).select_from(JobRun).where(JobRun.project_id==job_context.project))==1


@pytest.mark.parametrize('end',['SUCCESS','PARTIAL_ERROR','FAILED','CANCELED','SKIPPED'])
def test_transitions_and_terminal_reject(job_context,job,end):
    service=job_context.service
    service.transition_job(job,'RUNNING')
    service.transition_job(job,end,record_count=2)
    with job_context.factory() as s:
        row=s.get(JobRun,job);assert row.started_at and row.finished_at and row.record_count==2
    with pytest.raises(JobFailure,match='INVALID_JOB_TRANSITION'):service.transition_job(job,'RUNNING')
    assert service.create(job_context.project,'LIVE',job_context.provider)!=job


@pytest.mark.parametrize('end',['FAILED','SKIPPED','CANCELED'])
def test_pending_can_finish(job_context,job,end):
    job_context.service.transition_job(job,end)
    assert not job_context.service.claim(job)


@pytest.mark.parametrize('end',['SUCCESS','FAILED','PARTIAL_ERROR','SKIPPED','CANCELED'])
def test_terminal_redelivery_no_handler_calls(job_context,job,end):
    svc=job_context.service;svc.transition_job(job,'RUNNING');svc.transition_job(job,end)
    calls=[];runner=JobRunner(svc,lambda *a:calls.append(a))
    assert runner.execute(job)=='NO_OP' and runner.execute(job)=='NO_OP' and calls==[]


def test_running_delivery_no_op(job_context,job):
    svc=job_context.service;assert svc.claim(job)
    assert JobRunner(svc,lambda *a:pytest.fail('must not execute')).execute(job)=='NO_OP'


def test_optional_skips_normal_success(job_context,job):
    def handler(job_id,svc):
        for kind in PIPELINE[:2]:
            svc.transition_step(job_id,kind,'RUNNING')
            svc.transition_step(job_id,kind,'SUCCESS',record_count=2)
        for kind in PIPELINE[2:]:svc.transition_step(job_id,kind,'SKIPPED',result_summary={'reason':'capability_unavailable'})
    assert JobRunner(job_context.service,handler).execute(job)=='SUCCESS'
    with job_context.factory() as s:
        steps=job_context.service.repository.steps(s,job)
        assert [r.attempt_count for r in steps]==[1,1,0,0]
        assert s.get(JobRun,job).record_count==4


def test_runner_missing_and_failed_handler_safe(job_context,job):
    assert JobRunner(job_context.service).execute(job)=='FAILED'
    with job_context.factory() as s:
        row=s.get(JobRun,job);assert row.error_code=='JOB_HANDLER_NOT_IMPLEMENTED'
        assert [r.status for r in job_context.service.repository.steps(s,job)]==['FAILED','SKIPPED','SKIPPED','SKIPPED']
    second=job_context.service.create(job_context.project,'LIVE',job_context.provider)
    def bad(*args):raise RuntimeError('Bearer PRIVATE_DUMMY raw SQL')
    assert JobRunner(job_context.service,bad).execute(second)=='FAILED'
    with job_context.factory() as s:
        row=s.get(JobRun,second);assert row.error_code=='JOB_EXECUTION_ERROR' and 'PRIVATE_DUMMY' not in row.error_summary


def test_concurrent_deliveries_execute_once(job_context,job):
    entered,release=Event(),Event();calls=[]
    def handler(job_id,svc):
        calls.append(job_id);entered.set();assert release.wait(10)
        for kind in PIPELINE:svc.transition_step(job_id,kind,'SKIPPED')
    runner=JobRunner(job_context.service,handler)
    with ThreadPoolExecutor(2) as pool:
        first=pool.submit(runner.execute,job);assert entered.wait(10)
        second=pool.submit(runner.execute,job)
        try:assert second.result(timeout=10)=='NO_OP'
        finally:release.set()
        assert first.result(timeout=10)=='SKIPPED'
    assert calls==[job]


def test_step_order_and_incomplete_job_rejected(job_context,job):
    svc=job_context.service;svc.claim(job)
    with pytest.raises(JobFailure,match='JOB_STEP_OUT_OF_ORDER'):svc.transition_step(job,'TREND_REBUILD','RUNNING')
    with pytest.raises(JobFailure,match='JOB_STEPS_INCOMPLETE'):svc.finish(job)
    with pytest.raises(JobFailure,match='INVALID_JOB_TRANSITION'):svc.transition_step(job,'PROVIDER_SYNC','SUCCESS')


@pytest.mark.parametrize('metadata',[{'record_count':-1},{'error_count':-1},{'result_summary':{'token':'PRIVATE_DUMMY'}},{'error_summary':'Bearer PRIVATE_DUMMY'}])
def test_invalid_metadata_cannot_change_status(job_context,job,metadata):
    with pytest.raises(JobFailure):job_context.service.transition_job(job,'RUNNING',**metadata)
    with job_context.factory() as s:assert s.get(JobRun,job).status=='PENDING'
