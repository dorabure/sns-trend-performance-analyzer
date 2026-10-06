from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import delete, select, func, text
from app.db.models import JobRun, JobStep, ProviderConnection, Project, PostMetric, AccountMetric, ImportHistory
from app.db.models.job import STATUSES, PIPELINE
from tests.test_database import add, rejects, graph, NOW, TODAY


@pytest.fixture
def run(database, graph):
    return database.execute(select(JobRun.__table__)).mappings().one()


@pytest.mark.parametrize('model,field,bad', [
    (JobRun,'status','SYNCING'),(JobRun,'job_type','ANALYTICS_REFRESH'),(JobRun,'data_mode','BAD'),
    (JobRun,'record_count',-1),(JobRun,'error_count',-1),
    (JobStep,'status','PROCESSING'),(JobStep,'step_type','ANALYTICS_REFRESH'),
    (JobStep,'sequence_no',0),(JobStep,'sequence_no',-1),(JobStep,'attempt_count',-1),
    (JobStep,'record_count',-1),(JobStep,'error_count',-1),
])
def test_check_constraints(database, run, model, field, bad):
    values = ({'project_id':run['project_id'],'data_mode':'LIVE','job_type':'PROVIDER_SYNC','status':'SUCCESS'}
              if model is JobRun else {'job_run_id':run['id'],'step_type':'NORMALIZE_IMPORT','sequence_no':2})
    rejects(database, lambda:add(database,model,**{**values,field:bad}), '23514')


@pytest.mark.parametrize('status', STATUSES)
def test_all_job_and_step_statuses(database, run, status):
    database.execute(JobRun.__table__.update().values(status=status))
    database.execute(JobStep.__table__.update().values(status=status))
    assert database.scalar(select(JobRun.status)) == status
    assert database.scalar(select(JobStep.status)) == status


def test_active_scope_nulls_terminal_and_different_scopes(database, run):
    scope = {k:run[k] for k in ('project_id','data_mode','provider_connection_id','job_type')}
    for status in ('PENDING','RUNNING'):
        rejects(database,lambda st=status:add(database,JobRun,**scope,status=st),'23505')
    for status in ('SUCCESS','PARTIAL_ERROR','FAILED','SKIPPED','CANCELED'):
        add(database,JobRun,**scope,status=status)
    database.execute(JobRun.__table__.update().where(JobRun.id==run['id']).values(status='SUCCESS'))
    add(database,JobRun,**scope)
    provider = add(database,ProviderConnection,project_id=run['project_id'],provider_type='INSTAGRAM_API')
    add(database,JobRun,**{**scope,'provider_connection_id':provider['id']})
    p = add(database,Project,name='Other live',data_mode='LIVE')
    add(database,JobRun,**{**scope,'project_id':p['project_id'],'provider_connection_id':None})
    add(database,JobRun,**{**scope,'provider_connection_id':None})
    rejects(database,lambda:add(database,JobRun,**{**scope,'provider_connection_id':None}),'23505')


def test_step_uniques_and_defaults(database, run):
    for i, kind in enumerate(PIPELINE[1:],2):
        step=add(database,JobStep,job_run_id=run['id'],step_type=kind,sequence_no=i)
        assert step['status']=='PENDING' and step['attempt_count']==0 and step['result_summary']=={}
    rejects(database,lambda:add(database,JobStep,job_run_id=run['id'],step_type='PROVIDER_SYNC',sequence_no=5),'23505')
    database.execute(delete(JobStep).where(JobStep.step_type=='AI_INSIGHT_GENERATE'))
    rejects(database,lambda:add(database,JobStep,job_run_id=run['id'],step_type='AI_INSIGHT_GENERATE',sequence_no=2),'23505')


def test_delete_provider_preserves_job_project_cascades(database, run):
    from app.db.models import JobSchedule
    database.execute(delete(JobSchedule).where(JobSchedule.provider_connection_id==run['provider_connection_id']))
    database.execute(delete(ProviderConnection).where(ProviderConnection.id==run['provider_connection_id']))
    assert database.scalar(select(JobRun.provider_connection_id)) is None
    assert database.scalar(select(func.count()).select_from(JobStep))==1
    database.execute(delete(Project).where(Project.project_id==run['project_id']))
    assert database.scalar(select(func.count()).select_from(JobRun))==0
    assert database.scalar(select(func.count()).select_from(JobStep))==0


@pytest.mark.parametrize('model,owner,pk,time_field,instant', [
    (PostMetric,'post_id','post','recorded_at',NOW),
    (AccountMetric,'account_id','account','recorded_date',TODAY),
])
def test_metric_idempotency_and_legacy_unique(database,graph,run,model,owner,pk,time_field,instant):
    oid=graph[pk][owner]
    # Same owner/key cannot create a second snapshot even when timestamp changes.
    add(database,model,**{owner:oid,time_field:instant+timedelta(days=1),'ingest_key':'X_API:dummy:snapshot-1','ingest_job_run_id':run['id']})
    rejects(database,lambda:add(database,model,**{owner:oid,time_field:instant+timedelta(days=2),'ingest_key':'X_API:dummy:snapshot-1'}),'23505')
    rejects(database,lambda:add(database,model,**{owner:oid,time_field:instant,'ingest_key':'different'}),'23505')
    for n in (2,3):
        row=add(database,model,**{owner:oid,time_field:instant+timedelta(days=n)})
        assert row['ingest_key'] is None and row['ingest_job_run_id'] is None
    database.execute(delete(JobRun).where(JobRun.id==run['id']))
    assert database.scalar(select(func.count()).select_from(JobStep))==0
    assert database.scalar(select(model.ingest_job_run_id).where(model.ingest_key.is_not(None))) is None
    assert database.scalar(select(model.ingest_key).where(model.ingest_key.is_not(None)))=='X_API:dummy:snapshot-1'


def test_import_history_link_status_remains_independent(database,graph,run):
    database.execute(ImportHistory.__table__.update().values(job_run_id=run['id']))
    database.execute(delete(JobRun).where(JobRun.id==run['id']))
    history=database.execute(select(ImportHistory.__table__)).mappings().one()
    assert history['job_run_id'] is None and history['status']=='SUCCESS'
    rejects(database,lambda:database.execute(ImportHistory.__table__.update().values(status='PENDING')),'23514')


@pytest.mark.parametrize('model',[JobRun,JobStep])
@pytest.mark.parametrize('field,payload',[
    ('result_summary',{'nested':[{'access_token':'PRIVATE_DUMMY'}]}),
    ('result_summary',{'authorization':'PRIVATE_DUMMY'}),
    ('error_summary','Bearer PRIVATE_DUMMY'),('error_code','sk-proj-PRIVATE_DUMMY')])
def test_secret_metadata_rejected(database,run,model,field,payload):
    with pytest.raises(ValueError,match='Credentials are not allowed') as err:
        model(**{field:payload})
    assert 'PRIVATE_DUMMY' not in str(err.value)


def test_mutated_summary_revalidated_at_flush(database,run):
    from sqlalchemy.orm.attributes import flag_modified
    row=database.get(JobRun,run['id'])
    row.result_summary['secret']={'refresh_token':'PRIVATE_DUMMY'}
    flag_modified(row,'result_summary')
    with pytest.raises(ValueError,match='Credentials are not allowed'):
        database.flush()
