from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Query, Response
from app.api.v1.settings import SettingsRoute
from app.db.session import SessionLocal
from app.schemas.provider import ProviderType
from app.schemas.job_operations import ScheduleCreate, SchedulePatch
from app.services.job_operations_service import JobOperationsService, OperationsFailure

router = APIRouter(route_class=SettingsRoute, tags=['job-operations'])


def get_operations_service():
    return JobOperationsService(SessionLocal)


Service = Annotated[JobOperationsService, Depends(get_operations_service)]
Page = Annotated[int, Query(ge=1)]
Size = Annotated[int, Query(ge=1, le=100)]
Status = Literal['PENDING', 'RUNNING', 'SUCCESS', 'PARTIAL_ERROR', 'FAILED', 'SKIPPED', 'CANCELED']
Trigger = Literal['MANUAL', 'SCHEDULED', 'SYSTEM']


@router.post('/projects/{project_id}/providers/{provider_type}/sync', status_code=202)
def sync(project_id: UUID, provider_type: ProviderType, service: Service):
    return service.sync(project_id, provider_type)


@router.get('/projects/{project_id}/schedules')
def schedules(project_id: UUID, service: Service, page: Page = 1, page_size: Size = 50,
              enabled: bool | None = None, provider_type: ProviderType | None = None):
    return service.list_schedules(project_id, page, page_size, enabled, provider_type)


@router.post('/projects/{project_id}/schedules', status_code=201)
def create_schedule(project_id: UUID, body: ScheduleCreate, service: Service):
    return service.create_schedule(project_id, body)


@router.get('/projects/{project_id}/schedules/{schedule_id}')
def schedule(project_id: UUID, schedule_id: UUID, service: Service):
    return service.get_schedule(project_id, schedule_id)


@router.patch('/projects/{project_id}/schedules/{schedule_id}')
def patch_schedule(project_id: UUID, schedule_id: UUID, body: SchedulePatch, service: Service):
    return service.patch_schedule(project_id, schedule_id, body)


@router.delete('/projects/{project_id}/schedules/{schedule_id}', status_code=204)
def delete_schedule(project_id: UUID, schedule_id: UUID, service: Service):
    service.delete_schedule(project_id, schedule_id)
    return Response(status_code=204)


@router.post('/projects/{project_id}/schedules/{schedule_id}/enable')
def enable(project_id: UUID, schedule_id: UUID, service: Service):
    return service.set_enabled(project_id, schedule_id, True)


@router.post('/projects/{project_id}/schedules/{schedule_id}/disable')
def disable(project_id: UUID, schedule_id: UUID, service: Service):
    return service.set_enabled(project_id, schedule_id, False)


@router.post('/projects/{project_id}/schedules/{schedule_id}/run-now', status_code=202)
def run_now(project_id: UUID, schedule_id: UUID, service: Service):
    return service.run_now(project_id, schedule_id)


@router.get('/projects/{project_id}/jobs')
def jobs(project_id: UUID, service: Service, page: Page = 1, page_size: Size = 50,
         status: Status | None = None, provider_type: ProviderType | None = None, trigger_type: Trigger | None = None,
         from_at: Annotated[datetime | None, Query(alias='from')] = None,
         to_at: Annotated[datetime | None, Query(alias='to')] = None):
    if any(value is not None and value.tzinfo is None for value in (from_at, to_at)) or (from_at and to_at and from_at > to_at):
        raise OperationsFailure(422, 'VALIDATION_ERROR')
    return service.list_jobs(project_id, page, page_size, status=status, provider_type=provider_type,
                             trigger_type=trigger_type, from_at=from_at, to_at=to_at)


@router.get('/projects/{project_id}/jobs/{job_id}')
def job(project_id: UUID, job_id: UUID, service: Service):
    return service.get_job(project_id, job_id)


@router.post('/projects/{project_id}/jobs/{job_id}/cancel')
def cancel(project_id: UUID, job_id: UUID, service: Service):
    return service.cancel(project_id, job_id)
