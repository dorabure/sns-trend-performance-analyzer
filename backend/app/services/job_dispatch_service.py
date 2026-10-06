"""DB-backed at-least-once delivery; publish failure never deletes an accepted job."""
import os
from datetime import datetime, timedelta, timezone
from sqlalchemy import or_, select
from app.core.live_operations import live_enabled
from app.db.models import JobRun, Project, ProviderConnection
from app.jobs.dispatch import dispatch_job


class JobDispatchService:
    def __init__(self, factory, publisher=None, enabled=None):
        self.factory, self.publisher = factory, publisher or dispatch_job
        self.enabled = enabled or live_enabled

    def reconcile(self, now=None, job_id=None):
        if not self.enabled():
            return 0
        now = now or datetime.now(timezone.utc)
        threshold = now - timedelta(seconds=max(1, int(os.getenv('JOB_REDISPATCH_SECONDS', '300'))))
        delivered = 0
        with self.factory() as session, session.begin():
            query = select(JobRun).where(JobRun.status == 'PENDING', JobRun.data_mode == 'LIVE',
                or_(JobRun.enqueued_at.is_(None), JobRun.enqueued_at <= threshold))
            if job_id is not None:
                query = query.where(JobRun.id == job_id)
            for job in session.scalars(query.order_by(JobRun.created_at).limit(50).with_for_update(skip_locked=True)):
                project, provider = session.get(Project, job.project_id), session.get(ProviderConnection, job.provider_connection_id)
                if not project or not project.is_active or project.data_mode != 'LIVE' or not provider or provider.project_id != job.project_id or not provider.enabled or provider.connection_status != 'CONNECTED':
                    continue
                try:
                    self.publisher(job.id)
                except Exception:
                    # No broker exception text (URLs/credentials) is persisted or logged.
                    break
                job.enqueued_at = now
                delivered += 1
        return delivered
