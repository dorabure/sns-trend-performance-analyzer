from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.settings import SettingsRoute
from app.db.session import SessionLocal
from app.schemas.insights import ErrorResponse, GenerateRequest, InsightResponse, LatestResponse
from app.schemas.my_account import AnalysisPlatform
from app.services.insight_service import InsightService
from app.services.insight_history_service import InsightHistoryService
from app.schemas.insight_history import InsightHistoryPage, InsightHistoryDetail, InsightComparePreviousResponse

router = APIRouter(route_class=SettingsRoute, tags=['insights'], responses={
    code: {'model': ErrorResponse} for code in (400, 404, 422, 500, 503)})


def get_insight_service():
    return InsightService(SessionLocal)


Service = Annotated[InsightService, Depends(get_insight_service)]


def get_insight_history_service():
    return InsightHistoryService(SessionLocal)


HistoryService = Annotated[InsightHistoryService, Depends(get_insight_history_service)]


@router.get('/projects/{project_id}/insights/history', response_model=InsightHistoryPage)
def history(project_id: UUID, service: HistoryService,
            platform: AnalysisPlatform | None = None,
            start: Annotated[date | None, Query(alias='from')] = None,
            end: Annotated[date | None, Query(alias='to')] = None,
            limit: Annotated[int, Query(ge=1, le=100)] = 20,
            cursor: Annotated[str | None, Query(min_length=1, max_length=1024)] = None):
    return service.history(project_id, platform, start, end, limit, cursor)


@router.get('/projects/{project_id}/insights/history/{insight_id}', response_model=InsightHistoryDetail)
def history_detail(project_id: UUID, insight_id: UUID, service: HistoryService):
    return service.detail(project_id, insight_id)


@router.get('/projects/{project_id}/insights/history/{insight_id}/compare-previous',
            response_model=InsightComparePreviousResponse)
def compare_previous(project_id: UUID, insight_id: UUID, service: HistoryService):
    return service.compare_previous(project_id, insight_id)


@router.get('/projects/{project_id}/insights/latest', response_model=LatestResponse)
def latest(project_id: UUID, start: Annotated[date, Query(alias='from')],
           end: Annotated[date, Query(alias='to')], service: Service,
           platform: AnalysisPlatform = AnalysisPlatform.ALL):
    return service.latest(project_id, service.filters(start, end, platform))


@router.post('/projects/{project_id}/insights/generate', response_model=InsightResponse, status_code=201)
def generate(project_id: UUID, body: GenerateRequest, service: Service):
    return service.generate(project_id, service.filters(body.start, body.end, body.platform))
