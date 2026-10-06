from uuid import uuid4
from sqlalchemy import inspect, text
from tests.postgres_support import disposable_database,migrate


def test_phase3_job_upgrade_downgrade_reupgrade():
    with disposable_database() as engine:
        migrate(engine,'upgrade','0003_v2_background_jobs')
        pid,pc,jid=uuid4(),uuid4(),uuid4()
        with engine.begin() as c:
            c.execute(text("INSERT INTO projects(project_id,name,data_mode) VALUES (:id,'Existing LIVE','LIVE')"),{'id':pid})
            c.execute(text("INSERT INTO provider_connections(id,project_id,provider_type) VALUES (:id,:p,'X_API')"),{'id':pc,'p':pid})
            c.execute(text("INSERT INTO job_runs(id,project_id,data_mode,provider_connection_id,job_type) VALUES (:id,:p,'LIVE',:pc,'PROVIDER_SYNC')"),{'id':jid,'p':pid,'pc':pc})
            c.execute(text("INSERT INTO job_steps(id,job_run_id,step_type,sequence_no) VALUES (:id,:j,'PROVIDER_SYNC',1)"),{'id':uuid4(),'j':jid})
            before={t:[dict(r) for r in c.execute(text('SELECT * FROM '+t)).mappings()] for t in ('projects','provider_connections','job_runs','job_steps')}
        for _ in range(2):
            migrate(engine,'upgrade','head')
            assert len(inspect(engine).get_table_names())==19
            with engine.connect() as c:
                assert c.execute(text('SELECT trigger_type,job_schedule_id,scheduled_for,enqueued_at FROM job_runs')).one()==('SYSTEM',None,None,None)
                for t,rows in before.items():
                    assert [dict(r) for r in c.execute(text('SELECT '+','.join(rows[0])+' FROM '+t)).mappings()]==rows
            migrate(engine,'downgrade','0003_v2_background_jobs')
            assert len(inspect(engine).get_table_names())==18
        migrate(engine,'upgrade','head')
