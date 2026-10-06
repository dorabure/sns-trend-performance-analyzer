from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.exceptions import RequestValidationError

from app.api.v1.settings import SettingsRoute
from app.db.session import SessionLocal
from app.schemas.competitors import Analytics, Distribution, TopPosts
from app.schemas.my_account import AnalysisPlatform
from app.services.competitor_service import CompetitorService
from app.services.settings_service import SettingsFailure

router = APIRouter(route_class=SettingsRoute, tags=["competitors"])


def get_competitor_service():
    return CompetitorService(SessionLocal)


Service = Annotated[CompetitorService, Depends(get_competitor_service)]


def filters(start: Annotated[date, Query(alias="from")], end: Annotated[date, Query(alias="to")],
            platform: AnalysisPlatform = AnalysisPlatform.ALL):
    return CompetitorService.filters(start, end, platform)


def selected_accounts(account_ids: Annotated[str, Query(max_length=1000,
    description="Comma-separated 1 to 3 distinct active COMPETITOR UUIDs; active OWN is added automatically")]):
    parts = account_ids.split(",")
    if not account_ids.strip() or not 1 <= len(parts) <= 3:
        raise SettingsFailure(400, "INVALID_SELECTION", "Select 1 to 3 Competitors")
    try:
        ids = [UUID(part.strip()) for part in parts]
    except ValueError:
        raise RequestValidationError([{"type": "value_error", "loc": ("query", "account_ids"),
                                       "msg": "Select valid Account UUIDs"}]) from None
    if len(set(ids)) != len(ids):
        raise SettingsFailure(400, "INVALID_SELECTION", "Select distinct Competitors")
    return ids


@router.get("/projects/{project_id}/competitors/analytics", response_model=Analytics)
def analytics(project_id: UUID, service: Service, criteria=Depends(filters), ids=Depends(selected_accounts)):
    return service.analytics(project_id, ids, criteria)


@router.get("/projects/{project_id}/competitors/topic-distribution", response_model=Distribution)
def topic_distribution(project_id: UUID, service: Service, criteria=Depends(filters), ids=Depends(selected_accounts)):
    return service.topic_distribution(project_id, ids, criteria)


@router.get("/projects/{project_id}/competitors/top-posts", response_model=TopPosts)
def top_posts(project_id: UUID, service: Service, criteria=Depends(filters), ids=Depends(selected_accounts),
              limit: Annotated[int, Query(ge=1, le=50)] = 10):
    return service.top_posts(project_id, ids, criteria, limit)
