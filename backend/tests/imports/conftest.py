from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

from app.api.v1.imports import get_import_service
from app.db.models import Project, ProjectPlatform, SNSAccount, WatchTerm, WatchTopic
from app.main import app
from app.services.import_service import ImportService
from tests.postgres_support import validate_test_database

T1 = datetime(2026, 10, 3, 1, tzinfo=timezone.utc)


@dataclass
class ImportContext:
    factory: object
    project_id: object
    own_id: object
    competitor_id: object
    topic_id: object
    terms: dict
    service: ImportService


@pytest.fixture
def context(postgres_engine):
    validate_test_database(postgres_engine.url.database, "")
    factory = sessionmaker(postgres_engine, expire_on_commit=False)
    with factory() as session, session.begin():
        project = Project(name="Import isolated project")
        session.add(project)
        session.flush()
        session.add(ProjectPlatform(project_id=project.project_id, platform="X"))
        own = SNSAccount(project_id=project.project_id, platform="X", account_name="dummy_demo", account_role="OWN")
        competitor = SNSAccount(project_id=project.project_id, platform="X", account_name="competitor", account_role="COMPETITOR")
        inactive = SNSAccount(project_id=project.project_id, platform="X", account_name="inactive", account_role="COMPETITOR", is_active=False)
        topic = WatchTopic(project_id=project.project_id, topic_name="AI")
        inactive_topic = WatchTopic(project_id=project.project_id, topic_name="Disabled", is_active=False)
        session.add_all([own, competitor, inactive, topic, inactive_topic])
        session.flush()
        terms = {}
        for value, key, kind in [("ChatGPT", "chatgpt", "KEYWORD"), ("AI", "ai", "KEYWORD"),
                                 ("生成AI", "生成ai", "KEYWORD"), ("#ChatGPT", "#chatgpt", "HASHTAG"),
                                 ("#生成AI", "#生成ai", "HASHTAG")]:
            term = WatchTerm(topic_id=topic.topic_id, term=value, normalized_term=key, term_type=kind)
            session.add(term)
            session.flush()
            terms[value] = term.term_id
        session.add_all([
            WatchTerm(topic_id=topic.topic_id, term="inactive", normalized_term="inactive", term_type="KEYWORD", is_active=False),
            WatchTerm(topic_id=inactive_topic.topic_id, term="disabled", normalized_term="disabled", term_type="KEYWORD")])
    yield ImportContext(factory, project.project_id, own.account_id, competitor.account_id,
                        topic.topic_id, terms, ImportService(factory, now_provider=lambda: T1))
    with factory() as session, session.begin():
        session.execute(delete(Project).where(Project.project_id == project.project_id))


@pytest.fixture
def client(context):
    app.dependency_overrides[get_import_service] = lambda: context.service
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_import_service, None)
