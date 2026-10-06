"""Synchronous, broker-independent job state machine and scope validation."""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import os
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.provider_metadata import safe_metadata
from app.db.models import JobRun, JobStep, Project, ProviderConnection
from app.db.models.job import ACTIVE, TERMINAL, PIPELINE
from app.repositories.job_repository import JobRepository

TRANSITIONS = {
    'PENDING': frozenset(('RUNNING', 'FAILED', 'SKIPPED', 'CANCELED')),
    'RUNNING': frozenset(('SUCCESS', 'PARTIAL_ERROR', 'FAILED', 'SKIPPED', 'CANCELED')),
}


class JobFailure(Exception):
    def __init__(self, code, active_job_run_id=None):
        self.code = code
        self.active_job_run_id = active_job_run_id
        super().__init__(code)


class JobService:
    def __init__(self, session_factory, repository=None):
        self.factory = session_factory
        self.repository = repository or JobRepository()

    @contextmanager
    def transaction(self):
        try:
            with self.factory() as session, session.begin():
                yield session
        except JobFailure:
            raise
        except Exception:
            raise JobFailure('JOB_STORAGE_ERROR') from None

    def create(self, project_id, data_mode, provider_id, job_type='PROVIDER_SYNC', **metadata):
        try:
            with self.factory() as session, session.begin():
                return self.create_in_session(session, project_id, data_mode, provider_id, job_type, **metadata).id
        except JobFailure:
            raise
        except IntegrityError as error:
            if getattr(getattr(error.orig, 'diag', None), 'constraint_name', None) == 'uq_job_runs_active_scope':
                with self.transaction() as session:
                    active = self.repository.active(session, project_id, data_mode, provider_id, job_type)
                    active_id = active.id if active else None
                raise JobFailure('JOB_ALREADY_RUNNING', active_id) from None
            raise JobFailure('JOB_STORAGE_ERROR') from None
        except Exception:
            raise JobFailure('JOB_STORAGE_ERROR') from None

    def create_in_session(self, session, project_id, data_mode, provider_id, job_type='PROVIDER_SYNC', **metadata):
        project = session.get(Project, project_id)
        if project is None:
            raise JobFailure('PROJECT_NOT_FOUND')
        if not project.is_active:
            raise JobFailure('PROJECT_INACTIVE')
        if project.data_mode != data_mode:
            raise JobFailure('PROJECT_MODE_MISMATCH')
        if job_type != 'PROVIDER_SYNC' or data_mode != 'LIVE' or provider_id is None:
            raise JobFailure('INVALID_JOB_SCOPE')
        provider = session.get(ProviderConnection, provider_id)
        if provider is None:
            raise JobFailure('PROVIDER_NOT_FOUND')
        if provider.project_id != project_id:
            raise JobFailure('PROVIDER_PROJECT_MISMATCH')
        active = self.repository.active(session, project_id, data_mode, provider_id, job_type)
        if active:
            raise JobFailure('JOB_ALREADY_RUNNING', active.id)
        job = JobRun(project_id=project_id, data_mode=data_mode, provider_connection_id=provider_id, job_type=job_type, **metadata)
        session.add(job)
        session.flush()
        session.add_all([JobStep(job_run_id=job.id, step_type=kind, sequence_no=i)
                 for i, kind in enumerate(PIPELINE, 1)])
        session.flush()
        return job

    def run(self, session, job_id):
        job = self.repository.run(session, job_id)
        if job is None:
            raise JobFailure('JOB_NOT_FOUND')
        return job

    @staticmethod
    def transition(row, status, *, record_count=0, error_count=0, error_code=None, error_summary=None, result_summary=None):
        if status not in TRANSITIONS.get(row.status, ()):
            raise JobFailure('INVALID_JOB_TRANSITION')
        if type(record_count) is not int or type(error_count) is not int or min(record_count, error_count) < 0:
            raise JobFailure('INVALID_JOB_COUNTS')
        if error_code is not None and (not isinstance(error_code, str) or len(error_code) > 128):
            raise JobFailure('INVALID_JOB_METADATA')
        if error_summary is not None and (not isinstance(error_summary, str) or len(error_summary) > 1000):
            raise JobFailure('INVALID_JOB_METADATA')
        if result_summary is not None and not isinstance(result_summary, dict):
            raise JobFailure('INVALID_JOB_METADATA')
        try:
            for value in (error_code, error_summary, result_summary):
                safe_metadata(value)
        except ValueError:
            raise JobFailure('INVALID_JOB_METADATA') from None
        now = datetime.now(timezone.utc)
        row.status = status
        if status == 'RUNNING':
            row.started_at = now
            if isinstance(row, JobStep):
                row.attempt_count += 1
        else:
            row.finished_at = now
        row.record_count, row.error_count = record_count, error_count
        row.error_code, row.error_summary = error_code, error_summary
        row.result_summary = result_summary or {}

    def transition_job(self, job_id, status, **metadata):
        with self.transaction() as session:
            self.transition(self.run(session, job_id), status, **metadata)

    def claim(self, job_id):
        """A locked compare-and-transition; RUNNING/terminal delivery is a no-op."""
        with self.transaction() as session:
            job = self.run(session, job_id)
            if job.status != 'PENDING':
                return False
            self.transition(job, 'RUNNING')
            return True

    def transition_step(self, job_id, step_type, status, **metadata):
        with self.transaction() as session:
            job = self.run(session, job_id)
            if job.status != 'RUNNING':
                raise JobFailure('INVALID_JOB_TRANSITION')
            steps = self.repository.steps(session, job_id)
            step = next((s for s in steps if s.step_type == step_type), None)
            if step is None:
                raise JobFailure('JOB_STEP_NOT_FOUND')
            if any(s.status in ACTIVE for s in steps if s.sequence_no < step.sequence_no):
                raise JobFailure('JOB_STEP_OUT_OF_ORDER')
            self.transition(step, status, **metadata)

    def finish(self, job_id):
        with self.transaction() as session:
            job = self.run(session, job_id)
            steps = self.repository.steps(session, job_id)
            if len(steps) != 4 or any(s.status not in TERMINAL for s in steps):
                raise JobFailure('JOB_STEPS_INCOMPLETE')
            if job.status in TERMINAL:
                return job.status
            required = {s.status for s in steps if s.step_type in ('PROVIDER_SYNC', 'NORMALIZE_IMPORT')}
            optional = {s.status for s in steps if s.step_type not in ('PROVIDER_SYNC', 'NORMALIZE_IMPORT')}
            status = ('FAILED' if required & {'FAILED', 'CANCELED'} else
                      'PARTIAL_ERROR' if 'PARTIAL_ERROR' in required else
                      ('PARTIAL_ERROR' if optional & {'FAILED', 'PARTIAL_ERROR', 'CANCELED'} else 'SUCCESS') if required == {'SUCCESS'} else 'SKIPPED')
            self.transition(job, status, record_count=sum(s.record_count for s in steps),
                            error_count=sum(s.error_count for s in steps))
            return status

    def heartbeat(self, job_id, now=None):
        with self.transaction() as session:
            job = self.run(session, job_id)
            if job.status != 'RUNNING':
                return False
            job.updated_at = now or datetime.now(timezone.utc)
            return True

    def recover_stale(self, now=None, threshold=None):
        now = now or datetime.now(timezone.utc)
        try:
            threshold = int(threshold if threshold is not None else os.getenv('JOB_STALE_SECONDS', '900'))
            if not 300 <= threshold < 3600:
                raise ValueError()
        except (ValueError, TypeError):
            raise JobFailure('INVALID_STALE_THRESHOLD') from None
        with self.transaction() as session:
            rows = list(session.scalars(select(JobRun).where(JobRun.status == 'RUNNING',
                JobRun.updated_at < now - timedelta(seconds=threshold)).order_by(JobRun.updated_at, JobRun.id)
                .limit(50).with_for_update(skip_locked=True)))
            for job in rows:
                for step in self.repository.steps(session, job.id):
                    if step.status == 'RUNNING':
                        self.transition(step, 'FAILED', error_code='WORKER_HEARTBEAT_TIMEOUT', error_count=1,
                                        error_summary='Worker heartbeat timed out')
                    elif step.status == 'PENDING':
                        self.transition(step, 'SKIPPED', result_summary={'reason': 'worker_heartbeat_timeout'})
                self.transition(job, 'FAILED', error_code='WORKER_HEARTBEAT_TIMEOUT', error_count=1,
                                error_summary='Worker heartbeat timed out')
            return len(rows)

    def fail_execution(self, job_id, code):
        """Only fixed errors are used by the runner, never exception/provider text."""
        with self.transaction() as session:
            job = self.run(session, job_id)
            if job.status in TERMINAL:
                return
            steps = self.repository.steps(session, job_id)
            first = next((s for s in steps if s.status in ACTIVE), None)
            if first:
                self.transition(first, 'FAILED', error_code=code, error_summary='Job execution could not be completed', error_count=1)
            for step in steps:
                if step.status == 'PENDING':
                    self.transition(step, 'SKIPPED', result_summary={'reason': 'upstream_failed'})
            self.transition(job, 'FAILED', error_code=code, error_summary='Job execution could not be completed', error_count=1)
