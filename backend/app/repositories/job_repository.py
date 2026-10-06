from sqlalchemy import select
from app.db.models import JobRun, JobStep
from app.db.models.job import ACTIVE


class JobRepository:
    def active(self, session, project_id, data_mode, provider_id, job_type='PROVIDER_SYNC'):
        return session.scalar(select(JobRun).where(JobRun.project_id == project_id,
            JobRun.data_mode == data_mode, JobRun.provider_connection_id == provider_id,
            JobRun.job_type == job_type, JobRun.status.in_(ACTIVE)))

    def run(self, session, job_id):
        return session.scalar(select(JobRun).where(JobRun.id == job_id).with_for_update())

    def steps(self, session, job_id):
        return list(session.scalars(select(JobStep).where(JobStep.job_run_id == job_id).order_by(JobStep.sequence_no)))


