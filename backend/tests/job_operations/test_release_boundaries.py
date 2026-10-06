"""Release regression: capability changes cannot rewrite accepted job history."""
import pytest
from sqlalchemy import select

from app.db.models import JobRun, JobStep, ProviderConnection
from app.services.job_operations_service import OperationsFailure
from tests.job_operations.test_operations import NOW, due


def test_capability_loss_rejects_new_work_preserves_accepted_pipeline_and_cleanup(ops):
    sid = due(ops)
    accepted = ops.service.run_now(ops.pid, sid)
    jid = accepted['job_run_id']
    before = ops.service.get_job(ops.pid, jid)
    with ops.factory() as session, session.begin():
        connection = session.get(ProviderConnection, ops.provider)
        connection.capabilities = ['ACCOUNT_PROFILE']
    for action in (lambda: ops.service.sync(ops.pid, 'X_API'),
                   lambda: ops.service.run_now(ops.pid, sid),
                   lambda: ops.service.set_enabled(ops.pid, sid, True)):
        with pytest.raises(OperationsFailure) as error:
            action()
        assert error.value.code == 'PROVIDER_CAPABILITY_UNAVAILABLE'
    assert ops.service.tick(NOW) == 0
    assert ops.calls == [jid]
    assert ops.service.get_job(ops.pid, jid) == before
    with ops.factory() as session:
        assert len(session.scalars(select(JobRun).where(JobRun.project_id == ops.pid)).all()) == 1
        assert len(session.scalars(select(JobStep).where(JobStep.job_run_id == jid)).all()) == 4
    assert ops.service.set_enabled(ops.pid, sid, False)['enabled'] is False
    ops.service.delete_schedule(ops.pid, sid)
    after = ops.service.get_job(ops.pid, jid)
    assert after['job_schedule_id'] is None
    assert after['status'] == before['status']
    assert after['steps'] == before['steps']
