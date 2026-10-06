from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends
from app.api.v1.settings import SettingsRoute
from app.db.session import SessionLocal
from app.providers.x_oauth import XOAuthService
from app.providers.core import ProviderError
from app.services.settings_service import SettingsFailure

router = APIRouter(route_class=SettingsRoute, tags=['X OAuth'])


def get_x_oauth_service():
    return XOAuthService(SessionLocal)


Service = Annotated[XOAuthService, Depends(get_x_oauth_service)]


def safe_call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except ProviderError as error:
        raise SettingsFailure(409, error.code, 'Provider operation could not be completed') from None


@router.post('/projects/{project_id}/providers/X_API/oauth/start')
def start(project_id: UUID, service: Service):
    return safe_call(service.start, project_id)


@router.get('/providers/X_API/oauth/callback')
def callback(service: Service, state: str | None = None, code: str | None = None, error: str | None = None):
    return safe_call(service.callback, state=state, code=code, error=error)
