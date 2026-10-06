from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import ImportHistory
from app.services.import_recovery import recover_interrupted_imports, INTERRUPTED
from app.main import app


def histories(context):
    with context.factory() as session:
        return session.scalars(select(ImportHistory).where(ImportHistory.project_id == context.project_id)
                               .order_by(ImportHistory.import_id)).all()


@pytest.mark.parametrize('count', [0, 1, 5])
def test_startup_recovery_atomic_idempotent_preserves_counts(context, monkeypatch, count, caplog):
    stamp = datetime(2026, 10, 1, tzinfo=timezone.utc)
    original = {"row": 2, "field": "likes", "code": "INVALID_INTEGER", "message": "Invalid integer"}
    with context.factory() as session, session.begin():
        for status in ['PROCESSING'] * count + ['SUCCESS', 'PARTIAL_ERROR', 'FAILED']:
            session.add(ImportHistory(project_id=context.project_id, import_type='OWN_POSTS',
                filename='secret_path_never_logged.csv', status=status, total_count=7,
                success_count=3, error_count=2, imported_at=stamp, error_detail=[original]))
    before = {r.import_id: r.status for r in histories(context)}
    calls = []
    def startup(factory):
        calls.append(recover_interrupted_imports(context.factory))
    monkeypatch.setattr('app.main.recover_interrupted_imports', startup)
    with TestClient(app):
        after = histories(context)
        assert all(r.status == ('FAILED' if before[r.import_id] == 'PROCESSING' else before[r.import_id]) for r in after)
        for row in after:
            assert (row.total_count, row.success_count, row.error_count, row.imported_at) == (7, 3, 2, stamp)
            assert row.error_detail == [original] + ([INTERRUPTED] if before[row.import_id] == 'PROCESSING' else [])
    with TestClient(app):
        assert [(r.status, r.error_detail) for r in histories(context)] == [(r.status, r.error_detail) for r in after]
    assert calls == [count, 0]
    assert 'secret_path' not in caplog.text


def test_recovery_failure_safe_and_prevents_startup(monkeypatch, caplog):
    def broken():
        raise RuntimeError('SELECT password=PRIVATE_SECRET C:/private/file.csv')
    monkeypatch.setattr('app.main.SessionLocal', broken)
    monkeypatch.setattr('app.main.recover_interrupted_imports', recover_interrupted_imports)
    with pytest.raises(RuntimeError, match='Import recovery could not complete') as error:
        with TestClient(app):
            pytest.fail('Serving before recovery completed')
    assert 'PRIVATE_SECRET' not in str(error.value) + caplog.text
    assert 'IMPORT_RECOVERY_FAILED' in caplog.text


def test_first_install_without_migration_does_not_create_schema():
    from sqlalchemy import inspect
    from sqlalchemy.orm import sessionmaker
    from tests.postgres_support import disposable_database
    with disposable_database() as engine:
        assert recover_interrupted_imports(sessionmaker(engine)) == 0
        assert inspect(engine).get_table_names() == []
