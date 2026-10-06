from uuid import uuid4
from sqlalchemy import text,inspect
from tests.postgres_support import disposable_database,migrate


def test_existing_v2_upgrade_roundtrip_preserves_data():
    with disposable_database() as engine:
        migrate(engine,'upgrade','0002_v2_data_mode_and_providers')
        pid,pc,aid,post=uuid4(),uuid4(),uuid4(),uuid4()
        with engine.begin() as c:
            c.execute(text("INSERT INTO projects(project_id,name,data_mode) VALUES (:id,'Original Live','LIVE')"),{'id':pid})
            c.execute(text("INSERT INTO provider_connections(id,project_id,provider_type) VALUES (:id,:p,'X_API')"),{'id':pc,'p':pid})
            c.execute(text("INSERT INTO sns_accounts(account_id,project_id,platform,account_name,account_role,data_origin,provider_connection_id) VALUES (:id,:p,'X','original','OWN','X_API',:pc)"),{'id':aid,'p':pid,'pc':pc})
            c.execute(text("INSERT INTO sns_posts(post_id,project_id,account_id,platform,source_type,platform_post_id,posted_at,data_origin,provider_connection_id) VALUES (:id,:p,:a,'X','OWN','original',CURRENT_TIMESTAMP,'X_API',:pc)"),{'id':post,'p':pid,'a':aid,'pc':pc})
            c.execute(text("INSERT INTO post_metrics(post_metric_id,post_id,recorded_at,likes) VALUES (:id,:p,CURRENT_TIMESTAMP,0)"),{'id':uuid4(),'p':post})
            c.execute(text("INSERT INTO account_metrics(account_metric_id,account_id,recorded_date,followers) VALUES (:id,:a,'2026-10-04',0)"),{'id':uuid4(),'a':aid})
            c.execute(text("INSERT INTO import_histories(import_id,project_id,import_type,filename,status) VALUES (:id,:p,'OWN_POSTS','legacy.csv','SUCCESS')"),{'id':uuid4(),'p':pid})
            tables=('projects','provider_connections','sns_accounts','sns_posts','post_metrics','account_metrics','import_histories')
            before={t:[dict(r) for r in c.execute(text(f'SELECT * FROM {t}')).mappings()] for t in tables}
        unique={t:inspect(engine).get_unique_constraints(t) for t in ('post_metrics','account_metrics')}
        for _ in range(2):
            migrate(engine,'upgrade','0003_v2_background_jobs')
            with engine.connect() as c:
                assert c.scalar(text('SELECT version_num FROM alembic_version'))=='0003_v2_background_jobs'
                for table,rows in before.items():
                    cols=','.join(rows[0])
                    assert [dict(r) for r in c.execute(text(f'SELECT {cols} FROM {table}')).mappings()]==rows
                for t in ('post_metrics','account_metrics'):
                    assert c.execute(text(f'SELECT ingest_key,ingest_job_run_id FROM {t}')).one()==(None,None)
                    assert inspect(c).get_unique_constraints(t)==unique[t]
                assert c.scalar(text('SELECT job_run_id FROM import_histories')) is None
                assert c.scalar(text('SELECT count(*) FROM job_runs'))==0
            migrate(engine,'downgrade','0002_v2_data_mode_and_providers')
            assert len(inspect(engine).get_table_names())==16
        migrate(engine,'upgrade','0003_v2_background_jobs')
        assert len(inspect(engine).get_table_names())==18
