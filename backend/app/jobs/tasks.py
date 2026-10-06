import logging
from uuid import UUID
from celery.exceptions import Reject
from app.jobs.celery_app import app
from app.jobs.runner import JobRunner
from app.services.job_service import JobFailure, JobService
from app.core.live_operations import live_enabled

logger = logging.getLogger(__name__)


@app.task(name='sns.infrastructure_ping')
def infrastructure_ping():
    logger.warning('INFRASTRUCTURE_PONG')
    return 'PONG'


@app.task(name='sns.execute_job')
def execute_job(job_run_id):
    try:
        job_id = UUID(str(job_run_id))
    except (ValueError, TypeError, AttributeError):
        return 'INVALID_JOB_ID'
    if not live_enabled():
        return 'LIVE_MODE_DISABLED'
    try:
        # Lazy DB initialization keeps ping independent and catches unavailable DB safely.
        from app.db.session import SessionLocal
        from app.services.provider_sync_handler import ProviderSyncHandler
        return JobRunner(JobService(SessionLocal), ProviderSyncHandler(SessionLocal)).execute(job_id)
    except JobFailure as error:
        if error.code == 'JOB_NOT_FOUND':
            return 'JOB_NOT_FOUND'
        logger.warning('JOB_STORAGE_UNAVAILABLE job_run_id=%s', job_id)
        raise Reject('JOB_STORAGE_UNAVAILABLE', requeue=True) from None

    except Exception:
        logger.warning('JOB_STORAGE_UNAVAILABLE job_run_id=%s', job_id)
        raise Reject('JOB_STORAGE_UNAVAILABLE', requeue=True) from None


@app.task(name='sns.scheduler_tick')
def scheduler_tick():
    logger.warning('SCHEDULER_TICK')
    if not live_enabled():
        return 'LIVE_MODE_DISABLED'
    try:
        from app.db.session import SessionLocal
        from app.services.job_operations_service import JobOperationsService
        return JobOperationsService(SessionLocal).tick()
    except Exception:
        logger.warning('SCHEDULER_STORAGE_UNAVAILABLE')
        return 'SCHEDULER_STORAGE_UNAVAILABLE'
