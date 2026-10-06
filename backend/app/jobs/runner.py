from app.services.job_service import JobFailure


class JobRunner:
    def __init__(self, service, handler=None):
        self.service, self.handler = service, handler

    def execute(self, job_run_id):
        if not self.service.claim(job_run_id):
            return 'NO_OP'
        if self.handler is None:
            self.service.fail_execution(job_run_id, 'JOB_HANDLER_NOT_IMPLEMENTED')
            return 'FAILED'
        # Future handler: fetch -> normalize -> business commit -> sync-state checkpoint.
        # Never advance cursor/last_remote_id ahead of the business commit. Stable metric
        # ingest keys must identify provider/object/snapshot, independent of delivery/run UUID.
        # No production handler is registered in Phase 3. Injection is for state-machine tests.
        try:
            self.handler(job_run_id, self.service)
            return self.service.finish(job_run_id)
        except Exception:
            self.service.fail_execution(job_run_id, 'JOB_EXECUTION_ERROR')
            return 'FAILED'
