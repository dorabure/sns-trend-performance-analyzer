import pytest
from fastapi.testclient import TestClient

from app.api.v1.imports import get_import_service
from app.api.v1.settings import get_settings_service
from app.main import app
from app.services.settings_service import SettingsService
from tests.imports.conftest import context  # noqa: F401


@pytest.fixture
def settings(context):
    return SettingsService(context.factory)


@pytest.fixture
def client(context, settings):
    app.dependency_overrides[get_import_service] = lambda: context.service
    app.dependency_overrides[get_settings_service] = lambda: settings
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_import_service, None)
        app.dependency_overrides.pop(get_settings_service, None)
