from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.settings import SettingsRoute
from app.db.session import SessionLocal
from app.dto.normalized import MediaType
from app.schemas.my_account import Analytics, AnalysisPlatform, PostDetail, PostPage, SortField, SortOrder
from app.services.my_account_service import MyAccountService
from app.services.settings_service import SettingsFailure

router = APIRouter(route_class=SettingsRoute, tags=["my-account"])


def get_my_account_service():
    return MyAccountService(SessionLocal)


Service = Annotated[MyAccountService, Depends(get_my_account_service)]


def filters(start: Annotated[date, Query(alias="from")], end: Annotated[date, Query(alias="to")],
            platform: AnalysisPlatform | None = None, media_type: MediaType | None = None,
            keyword: Annotated[str | None, Query(max_length=1000)] = None,
            hashtag: Annotated[str | None, Query(max_length=255)] = None):
    return MyAccountService.filters(start, end, platform, media_type, keyword, hashtag)


@router.get("/projects/{project_id}/accounts/own/analytics", response_model=Analytics)
def analytics(project_id: UUID, service: Service, criteria=Depends(filters)):
    return service.analytics(project_id, criteria)


@router.get("/projects/{project_id}/accounts/own/posts", response_model=PostPage)
def posts(project_id: UUID, service: Service, criteria=Depends(filters),
          page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 20,
          sort: SortField = SortField.posted_at, order: SortOrder = SortOrder.desc):
    return service.posts(project_id, criteria, page, page_size, sort, order)


@router.get("/projects/{project_id}/posts/{post_id}", response_model=PostDetail)
def detail(project_id: UUID, post_id: UUID, service: Service,
           start: Annotated[date | None, Query(alias="from")] = None,
           end: Annotated[date | None, Query(alias="to")] = None,
           platform: AnalysisPlatform | None = None, media_type: MediaType | None = None,
           keyword: Annotated[str | None, Query(max_length=1000)] = None,
           hashtag: Annotated[str | None, Query(max_length=255)] = None):
    if (start is None) != (end is None):
        raise SettingsFailure(400, "INVALID_PERIOD", "Specify both start and end dates")
    if start is None and any(v is not None for v in (platform, media_type, keyword, hashtag)):
        raise SettingsFailure(400, "INVALID_PERIOD", "Specify dates when using comparison filters")
    criteria = service.filters(start, end, platform, media_type, keyword, hashtag) if start else None
    return service.detail(project_id, post_id, criteria)
