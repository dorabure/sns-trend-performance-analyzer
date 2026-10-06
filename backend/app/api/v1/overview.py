from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.settings import SettingsRoute
from app.db.session import SessionLocal
from app.schemas.my_account import AnalysisPlatform
from app.schemas.overview import MetricTrend, Overview, TrendMetric
from app.services.overview_service import OverviewService

router = APIRouter(route_class=SettingsRoute, tags=['overview'])


def get_overview_service():
    return OverviewService(SessionLocal)


@router.get('/projects/{project_id}/dashboard/overview', response_model=Overview)
def overview(project_id: UUID, start: Annotated[date, Query(alias='from')],
             end: Annotated[date, Query(alias='to')],
             service: Annotated[OverviewService, Depends(get_overview_service)],
             platform: AnalysisPlatform = AnalysisPlatform.ALL):
    return service.overview(project_id, service.filters(start, end, platform))


@router.get('/projects/{project_id}/dashboard/performance-trend', response_model=MetricTrend)
def performance_trend(project_id: UUID, start: Annotated[date, Query(alias='from')],
                      end: Annotated[date, Query(alias='to')], metric: TrendMetric,
                      service: Annotated[OverviewService, Depends(get_overview_service)],
                      platform: AnalysisPlatform = AnalysisPlatform.ALL):
    return service.performance_trend(project_id, service.filters(start, end, platform), metric)
