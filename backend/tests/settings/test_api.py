from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.db.models import ImportHistory, Project, SNSAccount
from tests.imports.conftest import T1


def base(context):
    return f"/api/v1/projects/{context.project_id}"


def test_project_lifecycle(client, context):
    response = client.post("/api/v1/projects", json={"name": " New ", "description": "draft", "platforms": ["X", "INSTAGRAM"]})
    assert response.status_code == 201
    created = response.json()
    path = f'/api/v1/projects/{created["project_id"]}'
    try:
        assert created["name"] == "New" and set(created["platforms"]) == {"X", "INSTAGRAM"}
        assert client.get(path).json() == created
        assert created in client.get("/api/v1/projects").json()
        for method in (client.put, client.patch):
            for body in ({"name": "Edited"}, {"description": None}, {"is_active": False}, {"is_active": True}):
                result = method(path, json=body)
                assert result.status_code == 200
                assert all(result.json()[key] == value for key, value in body.items())
        assert client.delete(path).status_code == 405
    finally:
        with context.factory() as s, s.begin():
            s.execute(delete(Project).where(Project.project_id == created["project_id"]))


@pytest.mark.parametrize("platforms", [[], ["ALL"], ["X", "X"], [None]])
def test_invalid_platforms(client, context, platforms):
    assert client.post("/api/v1/projects", json={"name": "P", "platforms": platforms}).status_code == 422
    assert client.put(base(context) + "/platforms", json={"platforms": platforms}).status_code == 422


@pytest.mark.parametrize("name", ["", "   ", "x" * 101, None])
def test_invalid_names(client, context, name):
    assert client.post("/api/v1/projects", json={"name": name, "platforms": ["X"]}).status_code == 422
    assert client.patch(base(context), json={"name": name}).status_code == 422


@pytest.mark.parametrize("platforms", [["X"], ["INSTAGRAM"], ["X", "INSTAGRAM"]])
def test_platform_roundtrip_preserves_accounts(client, context, platforms):
    response = client.put(base(context) + "/platforms", json={"platforms": platforms})
    assert response.status_code == 200 and set(response.json()["platforms"]) == set(platforms)
    assert client.get(base(context) + "/platforms").json() == response.json()
    assert len(client.get(base(context) + "/accounts").json()) == 3


def test_account_lifecycle_and_own_constraint(client, context):
    path = base(context) + "/accounts"
    own = {"platform": "X", "account_name": "second", "account_role": "OWN"}
    assert client.post(path, json=own).status_code == 409
    assert client.put(path + f"/{context.own_id}", json={"is_active": False}).status_code == 200
    created = client.post(path, json=own)
    assert created.status_code == 201
    assert client.patch(path + f"/{context.own_id}", json={"is_active": True}).status_code == 409
    new = created.json()
    assert client.delete(path + f'/{new["account_id"]}').json()["is_active"] is False
    assert client.patch(path + f"/{context.own_id}", json={"is_active": True}).status_code == 200
    account = client.post(path, json={**own, "account_role": "COMPETITOR", "account_name": " rival "}).json()
    edited = client.put(path + f'/{account["account_id"]}', json={"account_name": "new", "display_name": "Display", "profile_url": "https://example.com", "platform_account_id": "id"})
    assert edited.status_code == 200 and edited.json()["account_name"] == "new"
    assert client.patch(path + f'/{account["account_id"]}', json={"display_name": None}).json()["display_name"] is None
    listed = client.get(path).json()
    assert listed == sorted(listed, key=lambda a: (a["platform"], a["account_role"], a["account_name"]))
    with context.factory() as s:
        assert s.get(SNSAccount, new["account_id"]) is not None


@pytest.mark.parametrize("body", [{"platform": "INSTAGRAM"}, {"account_role": "COMPETITOR"}, {"account_name": None}, {"is_active": None}, {"display_name": "x" * 201}, {"platform_account_id": "x" * 256}])
def test_account_immutable_and_validation(client, context, body):
    assert client.patch(base(context) + f"/accounts/{context.own_id}", json=body).status_code == 422


def test_disabled_account_platform(client, context):
    path = base(context) + "/accounts"
    assert client.post(path, json={"platform": "INSTAGRAM", "account_name": "ig", "account_role": "OWN"}).status_code == 400
    assert client.patch(path + f"/{context.own_id}", json={"is_active": False}).status_code == 200
    client.put(base(context) + "/platforms", json={"platforms": ["INSTAGRAM"]})
    assert client.patch(path + f"/{context.own_id}", json={"is_active": True}).status_code == 400


def test_topic_and_term_lifecycle(client, context):
    path = base(context) + "/topics"
    created = client.post(path, json={"topic_name": " Extra ", "terms": [{"term": " ＡＢＣ ", "term_type": "KEYWORD"}]} )
    assert created.status_code == 201
    topic = created.json()
    assert topic["topic_name"] == "Extra" and topic["terms"][0]["normalized_term"] == "abc"
    tp = path + '/' + topic["topic_id"]
    assert client.post(path, json={"topic_name": "Extra"}).status_code == 409
    for body in ({"topic_name": "Renamed"}, {"description": "Description"}, {"is_active": False}, {"is_active": True}):
        result = client.put(tp, json=body)
        assert result.status_code == 200 and all(result.json()[k] == v for k, v in body.items())
    term_path = tp + "/terms"
    term = client.post(term_path, json={"term": "生成AI", "term_type": "HASHTAG"}).json()
    assert term["term"] == "#生成AI" and term["normalized_term"] == "#生成ai"
    assert client.post(term_path, json={"term": "#生成ai", "term_type": "HASHTAG"}).status_code == 409
    term_path += '/' + term["term_id"]
    for body in ({"term": "Claude"}, {"term_type": "KEYWORD"}, {"is_active": False}, {"is_active": True}):
        result = client.patch(term_path, json=body)
        assert result.status_code == 200
    assert result.json()["term_type"] == "KEYWORD" and result.json()["normalized_term"] == "#claude"
    assert client.delete(tp).json()["is_active"] is False
    topics = client.get(path).json()
    assert topics == sorted(topics, key=lambda t: t["topic_name"])


@pytest.mark.parametrize("value,expected", [("生成AI", "#生成AI"), ("#生成AI", "#生成AI"), ("#", None), ("#foo#bar", None), ("#foo bar", None), ("foo;bar", None), ("foo,bar", None), ("x" * 255, None)])
def test_hashtags(client, context, value, expected):
    topic = client.post(base(context) + "/topics", json={"topic_name": "Hashtag validation"}).json()
    result = client.post(base(context) + f'/topics/{topic["topic_id"]}/terms', json={"term": value, "term_type": "HASHTAG"})
    assert result.status_code == (201 if expected else 400)
    if expected:
        assert result.json()["term"] == expected


@pytest.mark.parametrize("body", [{"term": ""}, {"term": " "}, {"term_type": "OTHER"}, {"term_type": None}, {"is_active": None}, {"normalized_term": "client"}])
def test_term_validation(client, context, body):
    term_id = context.terms["ChatGPT"]
    path = base(context) + f"/topics/{context.topic_id}/terms/{term_id}"
    assert client.patch(path, json=body).status_code == 422


def test_term_collision(client, context):
    path = base(context) + f'/topics/{context.topic_id}/terms/{context.terms["ChatGPT"]}'
    assert client.patch(path, json={"term": "AI"}).status_code == 409
    topics = client.get(base(context) + "/topics").json()
    assert next(t for t in topics if t["topic_id"] == str(context.topic_id))["terms"]


def test_cross_resource_isolation(client, context):
    with context.factory() as s, s.begin():
        other = Project(name="Other")
        s.add(other); s.flush(); other_id = other.project_id
    try:
        path = f"/api/v1/projects/{other_id}"
        assert client.patch(path + f"/accounts/{context.own_id}", json={"display_name": "leak"}).status_code == 404
        assert client.patch(path + f"/topics/{context.topic_id}", json={"topic_name": "leak"}).status_code == 404
        assert client.post(path + f"/topics/{context.topic_id}/terms", json={"term": "leak", "term_type": "KEYWORD"}).status_code == 404
        assert client.patch(base(context) + f'/topics/{uuid4()}/terms/{context.terms["ChatGPT"]}', json={"term": "leak"}).status_code == 404
    finally:
        with context.factory() as s, s.begin():
            s.execute(delete(Project).where(Project.project_id == other_id))


def test_history_pagination_filters_detail(client, context):
    with context.factory() as s, s.begin():
        for i in range(25):
            s.add(ImportHistory(project_id=context.project_id, import_type="TREND_POSTS" if i % 2 else "OWN_POSTS",
                filename=f"file{i}.csv", total_count=1, success_count=0, error_count=1,
                status="FAILED" if i % 2 else "PARTIAL_ERROR", imported_at=T1 + timedelta(minutes=i),
                error_detail=[{"row": 2, "field": "likes", "code": "INVALID_INTEGER", "message": "Invalid number"}]))
    path = base(context) + "/imports"
    page = client.get(path).json()
    assert (len(page["items"]), page["total"], page["page_size"], page["limit"], page["offset"]) == (20, 25, 20, 20, 0)
    assert page["items"][0]["filename"] == "file24.csv"
    assert "error_detail" not in page["items"][0]
    assert len(client.get(path + "?page=2").json()["items"]) == 5
    assert len(client.get(path + "?limit=2&offset=24").json()["items"]) == 1
    assert client.get(path + "?status=FAILED&import_type=TREND_POSTS").json()["total"] == 12
    detail = client.get(path + '/' + page["items"][0]["import_id"])
    assert detail.status_code == 200 and detail.json()["error_detail"][0]["row"] == 2
    assert client.get(path + '/' + str(uuid4())).status_code == 404
    assert client.get(f'/api/v1/projects/{uuid4()}/imports/{page["items"][0]["import_id"]}').status_code == 404


@pytest.mark.parametrize("query", ["limit=101", "limit=0", "offset=-1", "page=0", "page_size=101", "status=BAD", "import_type=BAD"])
def test_history_query_validation(client, context, query):
    assert client.get(base(context) + "/imports?" + query).status_code == 422


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
def test_cors(client, method):
    r = client.options("/api/v1/projects", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": method, "Access-Control-Request-Headers": "content-type"})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_validation_does_not_echo_input(client, context):
    marker = "password-super-secret"
    r = client.patch(base(context), json={"unknown": marker})
    assert r.status_code == 422 and marker not in r.text
    assert client.get("/api/v1/projects/not-a-uuid").status_code == 422
    assert client.get(f"/api/v1/projects/{uuid4()}").status_code == 404
