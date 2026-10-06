from dataclasses import replace
from unittest.mock import Mock
import json

import anyio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.v1 import imports
from app.core.config import get_settings
from app.core.import_request_limit import ImportRequestLimit
from app.db.models import ImportHistory
from app.providers.base import CsvDatasetType as D
from tests.providers.helpers import csv_text, row


def multipart(content):
    return (b'--boundary\r\nContent-Disposition: form-data; name="import_type"\r\n\r\nOWN_POSTS\r\n'
            b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="PRIVATE_FILENAME.csv"\r\n'
            b'Content-Type: text/csv\r\n\r\n' + content + b'\r\n--boundary--\r\n')


def test_app(context, limit):
    app = FastAPI()
    app.add_middleware(ImportRequestLimit, max_bytes=limit)
    app.include_router(imports.router, prefix='/api/v1')
    app.dependency_overrides[imports.get_import_service] = lambda: context.service
    return app
test_app.__test__ = False


def send_chunks(app, context, chunks, declared=None, content_type=b'multipart/form-data; boundary=boundary'):
    async def run():
        messages = []
        headers = [(b'content-type', content_type)]
        if declared is not None:
            headers.append((b'content-length', str(declared).encode()))
        scope = {'type': 'http', 'http_version': '1.1', 'method': 'POST', 'scheme': 'http',
            'path': f'/api/v1/projects/{context.project_id}/imports', 'query_string': b'',
            'root_path': '', 'headers': headers, 'server': ('test', 80), 'client': ('test', 123)}
        iterator = iter(chunks)
        received = []
        async def receive():
            chunk = next(iterator)
            received.append(chunk)
            return {'type': 'http.request', 'body': chunk, 'more_body': len(received) < len(chunks)}
        async def send(message):
            messages.append(message)
        await app(scope, receive, send)
        return messages[0]['status'], json.loads(b''.join(m.get('body', b'') for m in messages[1:])), len(received)
    return anyio.run(run)


@pytest.mark.parametrize('declared', [None, 1, 'invalid'])
def test_stream_limit_closes_partial_spools_without_history(context, monkeypatch, tmp_path, declared):
    import starlette.formparsers as parser
    monkeypatch.setattr(imports.tempfile, 'tempdir', str(tmp_path))
    spools = []
    original = parser.SpooledTemporaryFile
    def capture(*args, **kwargs):
        file = original(*args, **kwargs); spools.append(file); return file
    monkeypatch.setattr(parser, 'SpooledTemporaryFile', capture)
    # First chunk parses the file headers and rolls a spool to disk; next chunk
    # breaches the limit and must not be passed to the parser. No timing assertion.
    first = multipart(b'PRIVATE_BODY' + b'x' * 1048577)[:-16]
    start = Mock(wraps=context.service.start)
    monkeypatch.setattr(context.service, 'start', start)
    status, body, received = send_chunks(test_app(context, len(first) + 3), context,
        [first, b'xxxx', b'never read'], declared)
    assert status == 413 and body['errors'][0]['code'] == 'REQUEST_TOO_LARGE'
    assert received == 2 and not start.called
    assert spools and all(file.closed for file in spools)
    assert not list(tmp_path.iterdir())
    with context.factory() as session:
        assert not session.scalars(select(ImportHistory)).all()
    assert 'PRIVATE' not in json.dumps(body)


def test_declared_limit_rejected_without_receive_or_route(context, monkeypatch):
    start = Mock(); monkeypatch.setattr(context.service, 'start', start)
    status, body, received = send_chunks(test_app(context, 10), context, [b'PRIVATE_BODY'], 11)
    assert status == 413 and received == 0 and not start.called
    assert 'PRIVATE' not in json.dumps(body)


@pytest.mark.parametrize('file_over', [False, True])
def test_request_boundary_and_independent_file_limit(context, monkeypatch, tmp_path, file_over):
    content = csv_text(D.OWN_POSTS, [row(D.OWN_POSTS)]).encode()
    body = multipart(content)
    monkeypatch.setattr(imports.tempfile, 'tempdir', str(tmp_path))
    monkeypatch.setattr(imports, 'get_settings', lambda: replace(get_settings(),
        max_import_file_size_bytes=len(content) - int(file_over)))
    status, result, _ = send_chunks(test_app(context, len(body)), context,
        [body[:100], body[100:]], declared=len(body))
    assert status == (413 if file_over else 200)
    assert result['status'] == ('FAILED' if file_over else 'SUCCESS')
    if file_over:
        assert result['errors'][0]['code'] == 'FILE_TOO_LARGE'
    with context.factory() as session:
        assert all(r.status != 'PROCESSING' for r in session.scalars(select(ImportHistory)))
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('kind', [b'multipart/form-data', b'multipart/form-data; boundary=boundary'])
def test_invalid_multipart_safe_without_history(context, kind):
    status, body, _ = send_chunks(test_app(context, 1000), context, [b'PRIVATE_BODY'], content_type=kind)
    assert 400 <= status < 500 and 'PRIVATE_BODY' not in json.dumps(body)
    with context.factory() as session:
        assert not session.scalars(select(ImportHistory)).all()


@pytest.mark.parametrize('value', ['0', '-1', 'invalid'])
def test_invalid_request_limit_configuration(monkeypatch, value):
    monkeypatch.setenv('MAX_IMPORT_REQUEST_SIZE_BYTES', value); get_settings.cache_clear()
    try:
        with pytest.raises(ValueError): get_settings()
    finally: get_settings.cache_clear()


def test_default_request_limit_tracks_file_limit(monkeypatch):
    monkeypatch.delenv('MAX_IMPORT_REQUEST_SIZE_BYTES', raising=False)
    monkeypatch.setenv('MAX_IMPORT_FILE_SIZE_BYTES', '1234'); get_settings.cache_clear()
    try:
        assert get_settings().max_import_request_size_bytes == 1234 + 1048576
    finally: get_settings.cache_clear()
