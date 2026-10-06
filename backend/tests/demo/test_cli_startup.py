"""Exercise the real CLI's production session timeout on an empty database."""
import json
import os
import subprocess
import sys

from tests.postgres_support import disposable_database, migrate


def test_canonical_cli_with_production_database_session():
    with disposable_database() as engine:
        migrate(engine, 'upgrade', 'head')
        environment = dict(os.environ, POSTGRES_DB=engine.url.database, OPENAI_API_KEY='')
        result = subprocess.run(
            [sys.executable, '-m', 'app.demo.loader', '--anchor-date', '2026-10-04', '--seed', '1401'],
            env=environment, capture_output=True, text=True, timeout=240,
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert [(item['dataset'], item['status'], item['rows']) for item in data['imports']] == [
            ('OWN_POSTS', 'SUCCESS', 180), ('COMPETITOR_POSTS', 'SUCCESS', 540),
            ('ACCOUNT_DAILY', 'SUCCESS', 180), ('TREND_POSTS', 'SUCCESS', 4500),
        ]
        assert data['ai_model'] == 'demo-fixture'
        assert data['live_openai_calls'] == 0
