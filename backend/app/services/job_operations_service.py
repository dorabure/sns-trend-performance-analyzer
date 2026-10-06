"""Public operations and scheduler acceptance share the same database transaction."""
from datetime import datetime, timezone
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from pydantic import ValidationError
from app.core.live_operations import live_enabled
from app.db.models import JobRun, JobSchedule, JobStep, ProviderConnection
from app.services.settings_service import SettingsService, SettingsFailure
from app.services.job_service import JobService, JobFailure
from app.services.job_dispatch_service import JobDispatchService
from app.services.schedule_time import next_run
from app.schemas.job_operations import ScheduleFields
from app.providers.core import ProviderRegistry
from app.providers.readiness import sync_capabilities_available


class OperationsFailure(SettingsFailure):
    def __init__(self, status, code, active_job_run_id=None):
        super().__init__(status, code, 'Job operation could not be completed')
        self.active_job_run_id = active_job_run_id


class JobOperationsService(SettingsService):
    def __init__(self, factory, *, enabled=None, dispatcher=None, clock=None, registry=None):
        super().__init__(factory)
        self.enabled = enabled or live_enabled
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.registry = registry or ProviderRegistry()
        self.jobs = JobService(factory)
        self.dispatcher = dispatcher or JobDispatchService(factory, enabled=self.enabled)

    def live_project(self, session, pid):
        project = self.project(session, pid)
        if project.data_mode != 'LIVE':
            raise OperationsFailure(409, 'SCHEDULE_REQUIRES_LIVE')
        return project

    def ready(self, session, pid, provider_id):
        if not self.enabled():
            raise OperationsFailure(409, 'LIVE_MODE_DISABLED')
        project = self.live_project(session, pid)
        session.refresh(project, with_for_update=True)
        if not project.is_active:
            raise OperationsFailure(409, 'PROJECT_INACTIVE')
        provider = session.scalar(select(ProviderConnection).where(ProviderConnection.id == provider_id,
            ProviderConnection.project_id == pid).with_for_update().execution_options(populate_existing=True))
        if provider is None:
            raise OperationsFailure(404, 'NOT_FOUND')
        self.require_sync_capabilities(provider, require_stored=False)
        if not provider.enabled or provider.connection_status != 'CONNECTED':
            raise OperationsFailure(409, 'PROVIDER_NOT_READY')
        self.require_sync_capabilities(provider)
        return provider

    def require_sync_capabilities(self, provider, *, require_stored=True):
        if not sync_capabilities_available(provider, self.registry, require_stored=require_stored):
            raise OperationsFailure(409, 'PROVIDER_CAPABILITY_UNAVAILABLE')

    def schedule(self, session, pid, sid, lock=False):
        self.live_project(session, pid)
        query = select(JobSchedule).where(JobSchedule.id == sid, JobSchedule.project_id == pid)
        row = session.scalar(query.with_for_update() if lock else query)
        if row is None:
            raise OperationsFailure(404, 'NOT_FOUND')
        return row

    @staticmethod
    def job_response(session, job, detail=False):
        keys = ('id', 'project_id', 'data_mode', 'provider_connection_id', 'job_type', 'job_schedule_id',
                'trigger_type', 'status', 'scheduled_for', 'enqueued_at', 'started_at', 'finished_at',
                'record_count', 'error_count', 'error_code', 'error_summary', 'created_at', 'updated_at')
        result = {k: getattr(job, k) for k in keys}
        provider = session.get(ProviderConnection, job.provider_connection_id) if job.provider_connection_id else None
        result['provider_type'] = provider.provider_type if provider else None
        result['duration_seconds'] = max(0, (job.finished_at - job.started_at).total_seconds()) if job.started_at and job.finished_at else None
        if detail:
            keys = ('id', 'step_type', 'sequence_no', 'status', 'attempt_count', 'started_at', 'finished_at',
                    'record_count', 'error_count', 'error_code', 'error_summary')
            result['steps'] = [{k: getattr(step, k) for k in keys} for step in session.scalars(
                select(JobStep).where(JobStep.job_run_id == job.id).order_by(JobStep.sequence_no))]
        return result

    def schedule_response(self, session, row):
        keys = ('id', 'project_id', 'provider_connection_id', 'schedule_type', 'schedule_mode', 'enabled',
                'interval_seconds', 'daily_time', 'timezone', 'next_run_at', 'last_run_at', 'last_job_run_id', 'created_at', 'updated_at')
        result = {k: getattr(row, k) for k in keys}
        result['provider_type'] = session.get(ProviderConnection, row.provider_connection_id).provider_type
        job = session.get(JobRun, row.last_job_run_id) if row.last_job_run_id else None
        result['last_job'] = {'id': job.id, 'status': job.status} if job else None
        return result

    def accept(self, session, pid, provider_id, trigger, schedule=None, due=None):
        self.ready(session, pid, provider_id)
        try:
            return self.jobs.create_in_session(session, pid, 'LIVE', provider_id,
                trigger_type=trigger, job_schedule_id=schedule.id if schedule else None, scheduled_for=due)
        except JobFailure as error:
            raise OperationsFailure(409, error.code, error.active_job_run_id) from None

    def accepted(self, session, job):
        provider = session.get(ProviderConnection, job.provider_connection_id)
        return dict(job_run_id=job.id, status='PENDING', job_type=job.job_type,
                    trigger_type=job.trigger_type, provider_type=provider.provider_type)

    def dispatch_accepted(self, job_id, now=None):
        try:
            self.dispatcher.reconcile(job_id=job_id, now=now)
        except Exception:
            pass  # Accepted DB row remains the recovery source after any delivery failure.

    def sync(self, pid, provider_type):
        with self.transaction() as session:
            self.live_project(session, pid)
            provider = session.scalar(select(ProviderConnection).where(ProviderConnection.project_id == pid,
                ProviderConnection.provider_type == provider_type))
            if provider is None:
                raise OperationsFailure(404, 'NOT_FOUND')
            job = self.accept(session, pid, provider.id, 'MANUAL')
            response = self.accepted(session, job)
        self.dispatch_accepted(job.id)
        return response

    def create_schedule(self, pid, body):
        try:
            with self.transaction() as session:
                self.live_project(session, pid)
                provider = self.entity(session, ProviderConnection, body.provider_connection_id, project_id=pid)
                self.require_sync_capabilities(provider, require_stored=False)
                scope = f'project:{pid}:provider:{body.provider_connection_id}:PROVIDER_SYNC_PIPELINE'
                if session.scalar(select(JobSchedule.id).where(JobSchedule.schedule_scope_key == scope)):
                    raise OperationsFailure(409, 'SCHEDULE_ALREADY_EXISTS')
                if body.enabled:
                    self.ready(session, pid, body.provider_connection_id)
                row = JobSchedule(project_id=pid, schedule_scope_key=scope, **body.model_dump())
                row.next_run_at = next_run(row, self.clock()) if row.enabled else None
                session.add(row); session.flush()
                return self.schedule_response(session, row)
        except SettingsFailure as error:
            if error.code == 'CONFLICT':
                raise OperationsFailure(409, 'SCHEDULE_ALREADY_EXISTS') from None
            raise

    def patch_schedule(self, pid, sid, body):
        with self.transaction() as session:
            row = self.schedule(session, pid, sid, True)
            values = {k: getattr(row, k) for k in ('schedule_mode', 'interval_seconds', 'daily_time', 'timezone')}
            values.update(body.model_dump(exclude_unset=True))
            try:
                fields = ScheduleFields(**values)
            except ValidationError:
                raise OperationsFailure(422, 'VALIDATION_ERROR') from None
            if row.enabled:
                self.ready(session, pid, row.provider_connection_id)
            for k, v in fields.model_dump().items():
                setattr(row, k, v)
            row.next_run_at = next_run(row, self.clock()) if row.enabled else None
            session.flush()
            return self.schedule_response(session, row)

    def set_enabled(self, pid, sid, enabled):
        with self.transaction() as session:
            row = self.schedule(session, pid, sid, True)
            if enabled:
                self.ready(session, pid, row.provider_connection_id)
            row.enabled = enabled
            row.next_run_at = next_run(row, self.clock()) if enabled else None
            session.flush()
            return self.schedule_response(session, row)

    def delete_schedule(self, pid, sid):
        with self.transaction() as session:
            session.delete(self.schedule(session, pid, sid, True))

    def run_now(self, pid, sid):
        with self.transaction() as session:
            row = self.schedule(session, pid, sid, True)
            job = self.accept(session, pid, row.provider_connection_id, 'MANUAL', row)
            response = self.accepted(session, job)
        self.dispatch_accepted(job.id)
        return response

    def get_schedule(self, pid, sid):
        with self.transaction() as session:
            return self.schedule_response(session, self.schedule(session, pid, sid))

    def list_schedules(self, pid, page=1, page_size=50, enabled=None, provider_type=None):
        with self.transaction() as session:
            self.project(session, pid)
            query = select(JobSchedule).join(ProviderConnection).where(JobSchedule.project_id == pid)
            if enabled is not None:
                query = query.where(JobSchedule.enabled == enabled)
            if provider_type:
                query = query.where(ProviderConnection.provider_type == provider_type)
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            rows = session.scalars(query.order_by(JobSchedule.created_at.desc(), JobSchedule.id).offset((page-1)*page_size).limit(page_size))
            return dict(items=[self.schedule_response(session, r) for r in rows], total=total, page=page, page_size=page_size)

    def list_jobs(self, pid, page=1, page_size=50, **filters):
        with self.transaction() as session:
            self.project(session, pid)
            query = select(JobRun).outerjoin(ProviderConnection).where(JobRun.project_id == pid)
            for key in ('status', 'trigger_type'):
                if filters.get(key):
                    query = query.where(getattr(JobRun, key) == filters[key])
            if filters.get('provider_type'):
                query = query.where(ProviderConnection.provider_type == filters['provider_type'])
            if filters.get('from_at'):
                query = query.where(JobRun.created_at >= filters['from_at'])
            if filters.get('to_at'):
                query = query.where(JobRun.created_at <= filters['to_at'])
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            rows = session.scalars(query.order_by(JobRun.created_at.desc(), JobRun.id).offset((page-1)*page_size).limit(page_size))
            return dict(items=[self.job_response(session, r) for r in rows], total=total, page=page, page_size=page_size)

    def get_job(self, pid, jid):
        with self.transaction() as session:
            self.project(session, pid)
            return self.job_response(session, self.entity(session, JobRun, jid, project_id=pid), True)

    def cancel(self, pid, jid):
        with self.transaction() as session:
            self.project(session, pid)
            row = session.scalar(select(JobRun).where(JobRun.id == jid, JobRun.project_id == pid).with_for_update())
            if row is None:
                raise OperationsFailure(404, 'NOT_FOUND')
            if row.status != 'PENDING':
                raise OperationsFailure(409, 'JOB_NOT_CANCELABLE')
            self.jobs.transition(row, 'CANCELED')
            for step in self.jobs.repository.steps(session, jid):
                if step.status == 'PENDING':
                    self.jobs.transition(step, 'CANCELED')
            session.flush()
            return self.job_response(session, row, True)

    def tick(self, now=None):
        if not self.enabled():
            return 0
        now = now or self.clock()
        self.jobs.recover_stale(now=now)
        accepted = []
        with self.transaction() as session:
            query = select(JobSchedule).where(JobSchedule.enabled.is_(True), JobSchedule.next_run_at <= now).order_by(
                JobSchedule.next_run_at, JobSchedule.id).limit(50).with_for_update(skip_locked=True)
            # Stable project lock order prevents cross-project batch deadlocks.
            rows = sorted(session.scalars(query), key=lambda row: (str(row.project_id), str(row.provider_connection_id)))
            for row in rows:
                due = row.next_run_at
                try:
                    job = self.accept(session, row.project_id, row.provider_connection_id, 'SCHEDULED', row, due)
                except OperationsFailure as error:
                    if error.code not in ('JOB_ALREADY_RUNNING', 'PROVIDER_NOT_READY', 'PROJECT_INACTIVE', 'PROVIDER_CAPABILITY_UNAVAILABLE'):
                        raise
                else:
                    row.last_run_at, row.last_job_run_id = now, job.id
                    accepted.append(job.id)
                row.next_run_at = next_run(row, now, due)
        # All schedule/job writes are committed before any broker operation.
        for job_id in accepted:
            self.dispatch_accepted(job_id, now=now)
        self.dispatcher.reconcile(now=now)
        return len(accepted)
