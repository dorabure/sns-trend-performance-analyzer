import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.api.v1.providers import get_provider_service
from app.api.v1.settings import get_settings_service
from app.api.v1.imports import get_import_service
from app.main import app
from app.db.models import Project
from app.services.provider_service import ProviderService
from app.services.settings_service import SettingsService
from tests.imports.conftest import context


@pytest.fixture
def client(context):
    old = dict(app.dependency_overrides)
    with context.factory() as session:
        before = set(session.scalars(select(Project.project_id)))
    app.dependency_overrides.update({
        get_provider_service: lambda: ProviderService(context.factory),
        get_settings_service: lambda: SettingsService(context.factory),
        get_import_service: lambda: context.service,
    })
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(old)
        with context.factory() as session, session.begin():
            session.execute(delete(Project).where(Project.project_id.not_in(before)))


@pytest.fixture
def live(client):
    response = client.post('/api/v1/projects', json={
        'name': 'V2 isolated live', 'platforms': ['X', 'INSTAGRAM'], 'data_mode': 'LIVE'})
    assert response.status_code == 201
    return response.json()['project_id']
