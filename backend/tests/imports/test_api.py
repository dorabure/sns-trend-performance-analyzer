from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import update

from app.api.v1 import imports as api
from app.core.config import get_settings
from app.db.models import ImportHistory, Project, SNSPost
from app.providers.base import CsvDatasetType as D
from tests.imports.test_pipeline import values
from tests.providers.helpers import csv_text, row


def upload(client, context, dataset=D.OWN_POSTS, content=None, filename="input.csv", project_id=None):
    return client.post(f"/api/v1/projects/{project_id or context.project_id}/imports",
        data={"import_type": dataset.value},
        files={"file": (filename, (content if content is not None else csv_text(dataset)).encode("utf-8"), "text/csv")})


@pytest.mark.parametrize("dataset", list(D))
def test_multipart_success_all_four_types(client, context, dataset):
    content = csv_text(dataset, [row(dataset, account_name="competitor" if dataset == D.COMPETITOR_POSTS else "dummy_demo")])
    response = upload(client, context, dataset, content)
    assert response.status_code == 200
    assert response.json()["status"] == "SUCCESS" and response.json()["success_count"] == 1
    assert response.json()["import_id"] == str(values(context, ImportHistory)[0].import_id)


@pytest.mark.parametrize("data,files", [({}, {"file": ("a.csv", b"anything")}),
    ({"import_type": "OWN_POSTS"}, {}), ({"import_type": "UNKNOWN"}, {"file": ("a.csv", b"anything")})])
def test_required_fields_and_invalid_type(client, context, data, files):
    response = client.post(f"/api/v1/projects/{context.project_id}/imports", data=data, files=files)
    assert response.status_code == 422
    assert not values(context, ImportHistory)


def test_partial_error_response(client, context):
    response = upload(client, context, content=csv_text(D.OWN_POSTS, [row(D.OWN_POSTS), row(D.OWN_POSTS, likes="bad")]))
    body = response.json()
    assert response.status_code == 200
    assert (body["status"], body["total_count"], body["success_count"], body["error_count"]) == ("PARTIAL_ERROR", 2, 1, 1)
    assert body["errors"][0]["row"] == 3 and body["errors"][0]["field"] == "likes"
    assert "row_number" not in body["errors"][0]


@pytest.mark.parametrize("content", ["broken header\n", "", csv_text(D.OWN_POSTS) + '"bad'])
def test_fatal_file_response(client, context, content):
    response = upload(client, context, content=content)
    assert response.status_code == 400
    assert response.json()["status"] == "FAILED"
    assert values(context, ImportHistory)[0].status == "FAILED"
    assert not values(context, SNSPost)


@pytest.mark.parametrize("inactive", [False, True])
def test_project_rejection(client, context, inactive):
    if inactive:
        with context.factory() as session, session.begin():
            session.execute(update(Project).where(Project.project_id == context.project_id).values(is_active=False))
    response = upload(client, context, project_id=context.project_id if inactive else uuid4())
    assert response.status_code == (409 if inactive else 404)
    assert response.json()["status"] == "FAILED"
    assert not values(context, ImportHistory)


def test_database_exception_sanitized_and_audited(client, context, monkeypatch):
    def broken(*args):
        raise RuntimeError("password=private_secret SELECT internal SQL traceback")
    monkeypatch.setattr(context.service.repository, "save_post", broken)
    response = upload(client, context)
    assert response.status_code == 500
    assert response.json()["errors"][0]["code"] == "IMPORT_DATABASE_ERROR"
    assert values(context, ImportHistory)[0].status == "FAILED"
    for sensitive in ("private_secret", "SELECT", "traceback", "password"):
        assert sensitive not in response.text


@pytest.mark.parametrize("filename", ["../evil.csv", r"C:\temp\evil.csv"])
def test_filename_is_basename_and_temp_removed(client, context, monkeypatch, tmp_path, filename):
    monkeypatch.setattr(api.tempfile, "tempdir", str(tmp_path))
    response = upload(client, context, filename=filename)
    assert response.status_code == 200
    assert values(context, ImportHistory)[0].filename == "evil.csv"
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("filename", ["a" * 256 + ".csv", ".."])
def test_invalid_filename_rejected(client, context, filename):
    response = upload(client, context, filename=filename)
    assert response.status_code == 400
    assert response.json()["errors"][0]["code"] == "INVALID_FILENAME"
    assert not values(context, ImportHistory)


@pytest.mark.parametrize("too_large", [False, True])
def test_size_boundary_and_temp_cleanup(client, context, monkeypatch, tmp_path, too_large):
    content = csv_text(D.OWN_POSTS)
    limit = len(content.encode("utf-8")) - int(too_large)
    monkeypatch.setattr(api, "get_settings", lambda: replace(get_settings(), max_import_file_size_bytes=limit))
    monkeypatch.setattr(api.tempfile, "tempdir", str(tmp_path))
    response = upload(client, context, content=content)
    assert response.status_code == (413 if too_large else 200)
    assert not list(tmp_path.iterdir())
    assert values(context, ImportHistory)[0].status == ("FAILED" if too_large else "SUCCESS")
    if too_large:
        assert not values(context, SNSPost)
        assert response.json()["errors"][0]["code"] == "FILE_TOO_LARGE"


def test_fatal_temp_cleanup(client, context, monkeypatch, tmp_path):
    monkeypatch.setattr(api.tempfile, "tempdir", str(tmp_path))
    assert upload(client, context, content="bad").status_code == 400
    assert not list(tmp_path.iterdir())


def test_database_failure_temp_cleanup(client, context, monkeypatch, tmp_path):
    monkeypatch.setattr(api.tempfile, "tempdir", str(tmp_path))
    def broken(*args):
        raise RuntimeError("fatal")
    monkeypatch.setattr(context.service.repository, "save_post", broken)
    assert upload(client, context).status_code == 500
    assert not list(tmp_path.iterdir())


def test_invalid_multipart_values_are_not_echoed(client, context):
    response = client.post(f"/api/v1/projects/{context.project_id}/imports",
        data={"import_type": "password=private_secret"}, files={"file": ("a.csv", b"csv")})
    assert response.status_code == 422 and "private_secret" not in response.text


def test_invalid_project_uuid_is_safe(client, context):
    response = client.post("/api/v1/projects/password=private_secret/imports",
        data={"import_type": "OWN_POSTS"}, files={"file": ("a.csv", b"csv")})
    assert response.status_code == 422 and "private_secret" not in response.text


def test_upload_write_failure_audited(client, context, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("internal filename password=secret")
    monkeypatch.setattr(api.tempfile, "NamedTemporaryFile", broken)
    response = upload(client, context)
    assert response.status_code == 500
    assert values(context, ImportHistory)[0].status == "FAILED"
    assert "secret" not in response.text


@pytest.mark.parametrize("origin,allowed", [("http://localhost:3000", True), ("https://unknown.example", False)])
def test_post_cors(client, context, origin, allowed):
    response = client.options(f"/api/v1/projects/{context.project_id}/imports", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Content-Type"})
    assert response.status_code == (200 if allowed else 400)
    assert ("access-control-allow-origin" in response.headers) == allowed
    if allowed:
        assert "POST" in response.headers["access-control-allow-methods"]
        assert "Content-Type" in response.headers["access-control-allow-headers"]


def test_unavailable_database_safe_without_history(client, context, monkeypatch):
    def broken():
        raise RuntimeError("connection string password=secret")
    monkeypatch.setattr(context.service, "session_factory", broken)
    response = upload(client, context)
    assert response.status_code == 500 and "secret" not in response.text
    assert not values(context, ImportHistory)


def test_failed_audit_logs_only_safe_message(context, tmp_path, monkeypatch, caplog):
    identifier, started = context.service.start(context.project_id, D.OWN_POSTS, "bad.csv")
    def broken():
        raise RuntimeError("password=secret SQL traceback")
    monkeypatch.setattr(context.service, "session_factory", broken)
    path = tmp_path / "bad.csv"
    path.write_text("bad")
    from app.services.import_service import ImportFailure
    with pytest.raises(ImportFailure):
        context.service.run(identifier, started, context.project_id, D.OWN_POSTS, path)
    assert "IMPORT_AUDIT_FAILED" in caplog.text
    assert "secret" not in caplog.text and "traceback" not in caplog.text


@pytest.mark.parametrize("value", ["0", "-1", "invalid"])
def test_invalid_size_configuration(monkeypatch, value):
    monkeypatch.setenv("MAX_IMPORT_FILE_SIZE_BYTES", value)
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError):
            get_settings()
    finally:
        get_settings.cache_clear()
