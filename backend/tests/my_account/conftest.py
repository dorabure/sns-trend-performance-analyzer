import pytest
from fastapi.testclient import TestClient

from app.api.v1.my_account import get_my_account_service
from app.main import app
from app.services.my_account_service import MyAccountService
from tests.imports.conftest import context  # noqa: F401


@pytest.fixture
def service(context):
    return MyAccountService(context.factory)


@pytest.fixture
def client(service):
    app.dependency_overrides[get_my_account_service] = lambda: service
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_my_account_service, None)
