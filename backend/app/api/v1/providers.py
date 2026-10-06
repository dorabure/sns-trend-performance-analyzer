from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.settings import SettingsRoute
from app.db.session import SessionLocal
from app.schemas.provider import ProviderType, ProviderPatch, ProviderResponse, ProviderDetail, ProjectContext
from app.schemas.provider import ProviderValidationResponse, ProviderCapabilitiesResponse
from app.services.provider_service import ProviderService

router = APIRouter(route_class=SettingsRoute, tags=["providers"])


def get_provider_service():
    return ProviderService(SessionLocal)


Service = Annotated[ProviderService, Depends(get_provider_service)]


@router.get("/projects/{project_id}/context", response_model=ProjectContext)
def context(project_id: UUID, service: Service):
    return service.context(project_id)


@router.get("/projects/{project_id}/providers", response_model=list[ProviderResponse])
def list_providers(project_id: UUID, service: Service):
    return service.list(project_id)


@router.get("/projects/{project_id}/providers/{provider_type}", response_model=ProviderDetail)
def provider_detail(project_id: UUID, provider_type: ProviderType, service: Service):
    return service.detail(project_id, provider_type)


@router.patch("/projects/{project_id}/providers/{provider_type}", response_model=ProviderResponse)
def patch_provider(project_id: UUID, provider_type: ProviderType, body: ProviderPatch, service: Service):
    return service.patch(project_id, provider_type, body)


@router.post('/projects/{project_id}/providers/{provider_type}/validate', response_model=ProviderValidationResponse)
def validate_provider(project_id: UUID, provider_type: ProviderType, service: Service):
    return service.validate(project_id, provider_type)


@router.get('/projects/{project_id}/providers/{provider_type}/capabilities', response_model=ProviderCapabilitiesResponse)
def provider_capabilities(project_id: UUID, provider_type: ProviderType, service: Service):
    return service.capabilities(project_id, provider_type)
