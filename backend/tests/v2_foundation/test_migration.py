from uuid import uuid4

from sqlalchemy import text, inspect
from tests.postgres_support import disposable_database, migrate


def test_legacy_upgrade_preserves_rows_keys_and_roundtrip():
    with disposable_database() as engine:
        migrate(engine, 'upgrade', '0001_initial')
        pid, aid, post = uuid4(), uuid4(), uuid4()
        with engine.begin() as c:
            c.execute(text('INSERT INTO projects(project_id,name) VALUES (:id, :name)'), {'id': pid, 'name': 'Legacy original'})
            c.execute(text("INSERT INTO project_platforms(project_platform_id,project_id,platform) VALUES (:id,:p,'X')"), {'id': uuid4(), 'p': pid})
            c.execute(text("INSERT INTO sns_accounts(account_id,project_id,platform,account_name,account_role,platform_account_id) VALUES (:id,:p,'X','legacy','OWN','remote-original')"), {'id': aid, 'p': pid})
            c.execute(text("INSERT INTO sns_posts(post_id,project_id,account_id,platform,source_type,platform_post_id,posted_at,text) VALUES (:id,:p,:a,'X','OWN','legacy-post',CURRENT_TIMESTAMP,'original')"), {'id': post, 'p': pid, 'a': aid})
            c.execute(text("INSERT INTO post_metrics(post_metric_id,post_id,recorded_at,likes) VALUES (:id,:p,CURRENT_TIMESTAMP,0)"), {'id': uuid4(), 'p': post})
            c.execute(text("INSERT INTO ai_insights(insight_id,project_id,analysis_from,analysis_to,content,model_name,prompt_version) VALUES (:id,:p,'2026-10-01','2026-10-04','{}','original-model','original-prompt')"), {'id': uuid4(), 'p': pid})
            tables = ['projects', 'project_platforms', 'sns_accounts', 'sns_posts', 'post_metrics', 'ai_insights']
            before = {t: [dict(row) for row in c.execute(text(f'SELECT * FROM {t}')).mappings()] for t in tables}
        original_constraints = {t: inspect(engine).get_unique_constraints(t) for t in ('sns_accounts', 'sns_posts')}
        original_indexes = {t: inspect(engine).get_indexes(t) for t in ('sns_accounts', 'sns_posts', 'post_metrics')}
        for _ in range(2):
            migrate(engine, 'upgrade', '0002_v2_data_mode_and_providers')
            with engine.connect() as c:
                assert c.scalar(text('SELECT data_mode FROM projects')) == 'DEMO'
                for t in ('sns_accounts', 'sns_posts'):
                    assert c.execute(text(f'SELECT data_origin,provider_connection_id FROM {t}')).one() == ('DEMO_CSV', None)
                assert c.scalar(text('SELECT count(*) FROM provider_connections')) == 0
                for t, rows in before.items():
                    columns = ','.join(rows[0].keys())
                    assert [dict(row) for row in c.execute(text(f'SELECT {columns} FROM {t}')).mappings()] == rows
            for t in original_constraints:
                assert inspect(engine).get_unique_constraints(t) == original_constraints[t]
            for t in original_indexes:
                assert inspect(engine).get_indexes(t) == original_indexes[t]
            migrate(engine, 'downgrade', '0001_initial')
            assert len(inspect(engine).get_table_names()) == 14
        migrate(engine, 'upgrade', '0002_v2_data_mode_and_providers')
        assert len(inspect(engine).get_table_names()) == 16
