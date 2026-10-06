from uuid import UUID
from fastapi import APIRouter, Query
from app.api.v1.settings import SettingsRoute
from app.db.session import SessionLocal
from app.providers.core import ProviderError
from app.providers.instagram_oauth import InstagramOAuthService
from app.services.settings_service import SettingsFailure

router = APIRouter(tags=['Instagram OAuth'], route_class=SettingsRoute)


def operation(method, *args, **kwargs):
    try:
        return getattr(InstagramOAuthService(SessionLocal), method)(*args, **kwargs)
    except ProviderError as error:
        raise SettingsFailure(409, error.code, 'Instagram OAuth operation failed') from None


@router.post('/projects/{project_id}/providers/INSTAGRAM_API/oauth/start')
def start(project_id: UUID):
    return operation('start', project_id)


@router.get('/providers/INSTAGRAM_API/oauth/callback')
def callback(state: str | None = Query(default=None), code: str | None = Query(default=None),
             error: str | None = Query(default=None)):
    return operation('callback', state=state, code=code, error=error)
