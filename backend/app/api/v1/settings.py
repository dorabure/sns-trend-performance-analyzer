from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.db.session import SessionLocal
from app.providers.base import CsvDatasetType
from app.schemas.settings import (AccountCreate, AccountPatch, AccountResponse, HistoryDetail, HistoryPage,
    ImportStatus, Platforms, ProjectCreate, ProjectPatch, ProjectResponse, TermCreate, TermPatch,
    TermResponse, TopicCreate, TopicPatch, TopicResponse)
from app.services.settings_service import SettingsFailure, SettingsService


class SettingsRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request):
            try:
                return await original(request)
            except SettingsFailure as exc:
                error = {"code": exc.code, "message": exc.message, "details": []}
                if getattr(exc, 'active_job_run_id', None) is not None:
                    error['active_job_run_id'] = str(exc.active_job_run_id)
                return JSONResponse(status_code=exc.status, content={"error": error})
            except RequestValidationError as exc:
                details = [{"loc": e["loc"], "type": e["type"], "message": "Request field is missing or invalid"}
                           for e in exc.errors()]
                return JSONResponse(status_code=422, content={"error": {
                    "code": "VALIDATION_ERROR", "message": "Check the request fields", "details": details}})
            except Exception:
                # Covers unexpected dependency/serialization failures too. Never
                # let framework traceback logging expose SQL or input contents.
                return JSONResponse(status_code=500, content={"error": {
                    "code": "INTERNAL_ERROR", "message": "Request could not be completed", "details": []}})
        return handle


router = APIRouter(route_class=SettingsRoute, tags=["settings"])


def get_settings_service():
    return SettingsService(SessionLocal)


Service = Annotated[SettingsService, Depends(get_settings_service)]


@router.get("/projects", response_model=list[ProjectResponse])
def list_projects(service: Service):
    return service.list_projects()


@router.post("/projects", response_model=ProjectResponse, status_code=201)
def create_project(body: ProjectCreate, service: Service):
    return service.create_project(body)


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(project_id: UUID, service: Service):
    return service.get_project(project_id)


@router.put("/projects/{project_id}", response_model=ProjectResponse)
@router.patch("/projects/{project_id}", response_model=ProjectResponse)
def patch_project(project_id: UUID, body: ProjectPatch, service: Service):
    return service.patch_project(project_id, body)


@router.get("/projects/{project_id}/platforms", response_model=Platforms)
def get_platforms(project_id: UUID, service: Service):
    return service.get_platforms(project_id)


@router.put("/projects/{project_id}/platforms", response_model=Platforms)
def put_platforms(project_id: UUID, body: Platforms, service: Service):
    return service.put_platforms(project_id, body)


@router.get("/projects/{project_id}/accounts", response_model=list[AccountResponse])
def list_accounts(project_id: UUID, service: Service):
    return service.list_accounts(project_id)


@router.post("/projects/{project_id}/accounts", response_model=AccountResponse, status_code=201)
def create_account(project_id: UUID, body: AccountCreate, service: Service):
    return service.create_account(project_id, body)


@router.put("/projects/{project_id}/accounts/{account_id}", response_model=AccountResponse)
@router.patch("/projects/{project_id}/accounts/{account_id}", response_model=AccountResponse)
def patch_account(project_id: UUID, account_id: UUID, body: AccountPatch, service: Service):
    return service.patch_account(project_id, account_id, body)


@router.delete("/projects/{project_id}/accounts/{account_id}", response_model=AccountResponse)
def deactivate_account(project_id: UUID, account_id: UUID, service: Service):
    return service.patch_account(project_id, account_id, AccountPatch(is_active=False))


@router.get("/projects/{project_id}/topics", response_model=list[TopicResponse])
def list_topics(project_id: UUID, service: Service):
    return service.list_topics(project_id)


@router.post("/projects/{project_id}/topics", response_model=TopicResponse, status_code=201)
def create_topic(project_id: UUID, body: TopicCreate, service: Service):
    return service.create_topic(project_id, body)


@router.put("/projects/{project_id}/topics/{topic_id}", response_model=TopicResponse)
@router.patch("/projects/{project_id}/topics/{topic_id}", response_model=TopicResponse)
def patch_topic(project_id: UUID, topic_id: UUID, body: TopicPatch, service: Service):
    return service.patch_topic(project_id, topic_id, body)


@router.delete("/projects/{project_id}/topics/{topic_id}", response_model=TopicResponse)
def deactivate_topic(project_id: UUID, topic_id: UUID, service: Service):
    return service.patch_topic(project_id, topic_id, TopicPatch(is_active=False))


@router.post("/projects/{project_id}/topics/{topic_id}/terms", response_model=TermResponse, status_code=201)
def create_term(project_id: UUID, topic_id: UUID, body: TermCreate, service: Service):
    return service.create_term(project_id, topic_id, body)


@router.patch("/projects/{project_id}/topics/{topic_id}/terms/{term_id}", response_model=TermResponse)
def patch_term(project_id: UUID, topic_id: UUID, term_id: UUID, body: TermPatch, service: Service):
    return service.patch_term(project_id, topic_id, term_id, body)


@router.get("/projects/{project_id}/imports", response_model=HistoryPage, tags=["imports"])
def histories(project_id: UUID, service: Service,
              page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 20,
              limit: Annotated[int | None, Query(ge=1, le=100)] = None,
              offset: Annotated[int | None, Query(ge=0)] = None,
              status: ImportStatus | None = None, import_type: CsvDatasetType | None = None):
    size = limit if limit is not None else page_size
    start = offset if offset is not None else (page - 1) * size
    return service.histories(project_id, size, start, status, import_type, start // size + 1, size)


@router.get("/projects/{project_id}/imports/{import_id}", response_model=HistoryDetail, tags=["imports"])
def history(project_id: UUID, import_id: UUID, service: Service):
    return service.history(project_id, import_id)
