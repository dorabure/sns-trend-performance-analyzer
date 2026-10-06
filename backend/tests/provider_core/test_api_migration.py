import json
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text, select
from app.main import app
from app.db.models import ProviderConnection, JobRun
from app.api.v1.providers import get_provider_service
from app.services.provider_service import ProviderService
from app.services.job_operations_service import JobOperationsService
from app.services.job_dispatch_service import JobDispatchService
from tests.postgres_support import disposable_database, migrate


def test_validate_capabilities_api_and_production_gate(live_context):
    c=live_context
    service=ProviderService(c.factory,registry=c.registry,resolver=c.resolver,enabled=lambda:True)
    app.dependency_overrides[get_provider_service]=lambda:service
    try:
        with TestClient(app) as client:
            base=f'/api/v1/projects/{c.project}/providers/{c.kind}'
            response=client.post(base+'/validate')
            assert response.status_code==200 and response.json()['valid']
            assert client.get(base+'/capabilities').json()['capabilities']['OWN_POSTS']
            assert client.post(f'/api/v1/projects/{uuid4()}/providers/{c.kind}/validate').status_code==404
            assert client.post(base.replace(c.kind,'OTHER')+'/validate').status_code==422
            app.dependency_overrides[get_provider_service]=lambda:ProviderService(c.factory,enabled=lambda:False)
            response=client.post(base+'/validate')
            assert response.status_code==409 and response.json()['error']['code']=='LIVE_MODE_DISABLED'
            app.dependency_overrides[get_provider_service]=lambda:ProviderService(c.factory,enabled=lambda:True)
            response=client.post(base+'/validate')
            expected = 'X_LIVE_SMOKE_DISABLED' if c.kind == 'X_API' else 'INSTAGRAM_LIVE_SMOKE_DISABLED'
            assert response.status_code==409 and response.json()['error']['code']==expected
            paths=client.get('/openapi.json').json()['paths']
            assert '/api/v1/projects/{project_id}/providers/{provider_type}/validate' in paths
            assert '/api/v1/projects/{project_id}/providers/{provider_type}/capabilities' in paths
            assert not any(path.startswith('/api/v2') for path in paths)
    finally:
        app.dependency_overrides.pop(get_provider_service,None)


def test_scheduler_recovers_stale_before_new_due_acceptance(live_context):
    from datetime import datetime, timezone, timedelta
    from app.schemas.job_operations import ScheduleCreate
    c=live_context
    with c.factory() as s,s.begin():
        row = s.get(ProviderConnection,c.provider)
        row.connection_status='CONNECTED'
        row.capabilities = sorted(v.value for v in c.remote.capabilities())
    now=datetime.now(timezone.utc)
    dispatched=[]
    dispatcher=JobDispatchService(c.factory,publisher=dispatched.append,enabled=lambda:True)
    ops=JobOperationsService(c.factory,enabled=lambda:True,clock=lambda:now,dispatcher=dispatcher,registry=c.registry)
    schedule=ops.create_schedule(c.project,ScheduleCreate(provider_connection_id=c.provider,schedule_mode='INTERVAL',interval_seconds=60,enabled=True))
    old=c.jobs.create(c.project,'LIVE',c.provider);c.jobs.claim(old)
    assert ops.tick(now=now+timedelta(seconds=901))==1
    with c.factory() as s:
        assert s.get(JobRun,old).status=='FAILED'
    assert len(dispatched)==1 and dispatched[0]!=old


def insert(connection,table,**values):
    from app.db.base import Base
    for column in Base.metadata.tables[table].primary_key:
        if column.name not in values:
            values[column.name]=uuid4()
    columns=','.join(values)
    params=','.join(':'+key for key in values)
    return connection.execute(text(f'INSERT INTO {table} ({columns}) VALUES ({params}) RETURNING *'),values).mappings().one()


def snapshot(engine):
    from sqlalchemy import inspect
    with engine.connect() as c:
        result={}
        for table in inspect(c).get_table_names():
            if table=='alembic_version':continue
            rows=[]
            for row in c.execute(text('SELECT * FROM '+table)).mappings():
                value=dict(row)
                if table=='import_histories':
                    value.pop('data_origin',None);value.pop('provider_connection_id',None)
                rows.append(value)
            result[table]=sorted(rows,key=lambda row:json.dumps(row,sort_keys=True,default=str))
        return result


def test_0004_business_rows_upgrade_downgrade_reupgrade_preserves_every_table():
    from datetime import date,datetime,timezone
    with disposable_database() as engine:
        migrate(engine,'upgrade','0004_v2_scheduler_ops')
        with engine.begin() as c:
            pid=insert(c,'projects',project_id=uuid4(),name='Migration preserved',data_mode='LIVE')['project_id']
            insert(c,'project_platforms',project_id=pid,platform='X')
            provider=insert(c,'provider_connections',id=uuid4(),project_id=pid,provider_type='X_API',enabled=True,connection_status='CONNECTED')['id']
            jid=insert(c,'job_runs',id=uuid4(),project_id=pid,provider_connection_id=provider,data_mode='LIVE',job_type='PROVIDER_SYNC',status='SUCCESS')['id']
            insert(c,'job_steps',id=uuid4(),job_run_id=jid,step_type='PROVIDER_SYNC',sequence_no=1,status='SUCCESS')
            insert(c,'job_schedules',id=uuid4(),project_id=pid,provider_connection_id=provider,schedule_mode='INTERVAL',interval_seconds=60,schedule_scope_key='migration-test')
            insert(c,'provider_sync_states',id=uuid4(),provider_connection_id=provider,sync_resource_type='POSTS',cursor='saved')
            account=insert(c,'sns_accounts',account_id=uuid4(),project_id=pid,platform='X',account_name='migration-own',account_role='OWN',data_origin='X_API',provider_connection_id=provider)['account_id']
            insert(c,'account_metrics',account_metric_id=uuid4(),account_id=account,recorded_date=date(2026,10,4),followers=0,ingest_key='stable-account',ingest_job_run_id=jid)
            post=insert(c,'sns_posts',post_id=uuid4(),project_id=pid,account_id=account,platform='X',platform_post_id='remote',source_type='OWN',posted_at=datetime.now(timezone.utc),data_origin='X_API',provider_connection_id=provider)['post_id']
            insert(c,'post_metrics',post_metric_id=uuid4(),post_id=post,recorded_at=datetime.now(timezone.utc),likes=0,ingest_key='stable-post',ingest_job_run_id=jid)
            topic=insert(c,'watch_topics',topic_id=uuid4(),project_id=pid,topic_name='test')['topic_id']
            term=insert(c,'watch_terms',term_id=uuid4(),topic_id=topic,term='test',normalized_term='test',term_type='KEYWORD')['term_id']
            insert(c,'post_topics',post_id=post,topic_id=topic,match_type='KEYWORD')
            insert(c,'post_terms',post_id=post,term_id=term,match_method='EXACT')
            insert(c,'trend_daily',topic_id=topic,platform='X',trend_date=date(2026,10,4))
            insert(c,'ai_insights',insight_id=uuid4(),project_id=pid,analysis_from=date(2026,10,4),analysis_to=date(2026,10,4),content='{}')
            insert(c,'import_histories',import_id=uuid4(),project_id=pid,import_type='OWN_POSTS',filename='preserved.csv',status='SUCCESS')
        before=snapshot(engine)
        assert len(before)==18 and all(before.values())
        for operation,revision in [('upgrade','head'),('downgrade','0004_v2_scheduler_ops'),('upgrade','head')]:
            migrate(engine,operation,revision)
            assert snapshot(engine)==before
        with engine.connect() as c:
            history=c.execute(text('SELECT data_origin,provider_connection_id,job_run_id FROM import_histories')).mappings().one()
            assert history['data_origin']=='DEMO_CSV' and history['provider_connection_id'] is None and history['job_run_id'] is None
        with engine.begin() as c:
            c.execute(text('UPDATE import_histories SET data_origin=:origin,provider_connection_id=:provider,job_run_id=:job'),{'origin':'X_API','provider':provider,'job':jid})
            c.execute(text('DELETE FROM job_schedules'))
            c.execute(text('DELETE FROM provider_connections'))
            assert c.execute(text('SELECT provider_connection_id FROM import_histories')).scalar_one() is None
