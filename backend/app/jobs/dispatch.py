"""Internal dispatch boundary; public operations/outbox belong to Phase 4."""
from uuid import UUID
from app.jobs.celery_app import app
from app.services.job_service import JobFailure


def dispatch_job(job_run_id):
    job_id = str(UUID(str(job_run_id)))
    try:
        return app.send_task('sns.execute_job', args=[job_id], argsrepr='(<job_run_id>,)', kwargsrepr='{}')
    except Exception:
        raise JobFailure('JOB_DISPATCH_UNAVAILABLE') from None
