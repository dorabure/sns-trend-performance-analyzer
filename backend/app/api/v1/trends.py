from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.settings import SettingsRoute
from app.db.session import SessionLocal
from app.schemas.my_account import AnalysisPlatform
from app.schemas.trends import Ranking, Timeseries, TopPosts, TrendMetric
from app.services.trend_explorer_service import TrendExplorerService

router = APIRouter(route_class=SettingsRoute, tags=["trends"])


def get_trend_explorer_service():
    return TrendExplorerService(SessionLocal)


Service = Annotated[TrendExplorerService, Depends(get_trend_explorer_service)]


def filters(start: Annotated[date, Query(alias="from")], end: Annotated[date, Query(alias="to")],
            platform: AnalysisPlatform = AnalysisPlatform.ALL,
            keyword: Annotated[str | None, Query(max_length=1000)] = None):
    return TrendExplorerService.filters(start, end, platform, keyword=keyword)


def selected_terms(term_ids: Annotated[str, Query(min_length=1, max_length=184,
    description="Comma-separated 1 to 5 distinct Term UUIDs")]):
    # Explicit safe validation through SettingsRoute's existing RequestValidationError envelope.
    from fastapi.exceptions import RequestValidationError
    try:
        ids = [UUID(part.strip()) for part in term_ids.split(",")]
        if not 1 <= len(ids) <= 5 or len(set(ids)) != len(ids):
            raise ValueError()
        return ids
    except ValueError:
        raise RequestValidationError([{"type": "value_error", "loc": ("query", "term_ids"),
                                       "msg": "Select 1 to 5 distinct Term UUIDs"}]) from None


@router.get("/projects/{project_id}/trends/ranking", response_model=Ranking)
def ranking(project_id: UUID, topic_id: UUID, service: Service, criteria=Depends(filters),
            limit: Annotated[int, Query(ge=1, le=100)] = 20):
    return service.ranking(project_id, topic_id, criteria, limit)


@router.get("/projects/{project_id}/trends/timeseries", response_model=Timeseries)
def timeseries(project_id: UUID, service: Service, criteria=Depends(filters),
               ids=Depends(selected_terms), metric: TrendMetric = TrendMetric.post_count):
    return service.timeseries(project_id, ids, criteria, metric)


@router.get("/projects/{project_id}/trends/{topic_id}/top-posts", response_model=TopPosts)
def top_posts(project_id: UUID, topic_id: UUID, service: Service, criteria=Depends(filters),
              limit: Annotated[int, Query(ge=1, le=50)] = 10, term_id: UUID | None = None):
    return service.top_posts(project_id, topic_id, criteria, limit, term_id)
