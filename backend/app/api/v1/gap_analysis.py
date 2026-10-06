from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.settings import SettingsRoute
from app.db.session import SessionLocal
from app.schemas.gap_analysis import GapAnalysis
from app.schemas.my_account import AnalysisPlatform
from app.services.gap_analysis_service import GapAnalysisService

router = APIRouter(route_class=SettingsRoute, tags=['gap-analysis'])


def get_gap_analysis_service():
    return GapAnalysisService(SessionLocal)


@router.get('/projects/{project_id}/gap-analysis', response_model=GapAnalysis)
def gap_analysis(project_id: UUID, start: Annotated[date, Query(alias='from')],
                 end: Annotated[date, Query(alias='to')],
                 service: Annotated[GapAnalysisService, Depends(get_gap_analysis_service)],
                 platform: AnalysisPlatform = AnalysisPlatform.ALL):
    return service.analysis(project_id, service.filters(start, end, platform))
