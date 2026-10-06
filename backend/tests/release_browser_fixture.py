"""Fictional Phase13 provider/history screenshots, disposable DB, zero external HTTP.

No production imports this module. The existing history fixture provides the
fake AI client and network guard. All provider names below are fictional.
"""
from contextlib import asynccontextmanager
from uuid import UUID

import uvicorn

from app.api.v1.settings import get_settings_service
from app.api.v1.providers import get_provider_service
from app.api.v1.job_operations import get_operations_service
from app.db.models import Project, ProjectPlatform, ProviderConnection
from app.services.provider_service import ProviderService
from app.services.job_operations_service import JobOperationsService
from tests.insights import history_browser_fixture as history

LIVE = UUID('00000000-0000-4000-8000-000000000113')


@asynccontextmanager
async def lifespan(application):
    async with history.lifespan(application):
        factory = application.dependency_overrides[get_settings_service]().session_factory
        with factory() as session, session.begin():
            session.add(Project(project_id=LIVE, name='Phase13 Fictional LIVE Provider Fixture', data_mode='LIVE'))
            session.flush()
            session.add(ProjectPlatform(project_id=LIVE, platform='X'))
            session.add(ProjectPlatform(project_id=LIVE, platform='INSTAGRAM'))
            for kind, caps in [('X_API', ['ACCOUNT_PROFILE', 'OWN_POSTS', 'OWN_METRICS']),
                               ('INSTAGRAM_API', ['ACCOUNT_PROFILE'])]:
                session.add(ProviderConnection(project_id=LIVE, provider_type=kind,
                    enabled=True, connection_status='CONNECTED', capabilities=caps,
                    remote_account_id='FICTIONAL_ONLY'))
        application.dependency_overrides[get_provider_service] = lambda: ProviderService(factory, enabled=lambda: True)
        application.dependency_overrides[get_operations_service] = lambda: JobOperationsService(factory, enabled=lambda: True)
        print('PHASE13_FICTIONAL_RELEASE_FIXTURE_READY external_calls=0', flush=True)
        yield


if __name__ == '__main__':
    history.app.router.lifespan_context = lifespan
    uvicorn.run(history.app, host='0.0.0.0', port=8000)
