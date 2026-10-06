from sqlalchemy import select, update

from app.db.base import Base
from app.db.models import Project, SNSAccount, WatchTerm, WatchTopic
from app.db.seed import DEMO_PROJECT_ID, demo_id, seed
from tests.test_database import add, count


def snapshot(database):
    return {name: sorted([tuple(row) for row in database.execute(select(table)).all()], key=str)
            for name, table in Base.metadata.tables.items()}


def test_seed_twice_is_identical(database):
    seed(database)
    database.commit()
    before = snapshot(database)
    seed(database)
    database.commit()
    assert snapshot(database) == before
    expected = {"projects": 1, "project_platforms": 2, "sns_accounts": 5, "watch_topics": 2, "watch_terms": 6}
    for name, table in Base.metadata.tables.items():
        assert count(database, table) == expected.get(name, 0)
    accounts = database.execute(select(SNSAccount.platform, SNSAccount.account_role, SNSAccount.is_active)).all()
    assert sorted((p, active) for p, role, active in accounts if role == "OWN") == [("INSTAGRAM", True), ("X", True)]
    assert {p for p, role, _ in accounts if role == "COMPETITOR"} == {"X", "INSTAGRAM"}
    assert len(Base.metadata.tables) == 18


def test_seed_preserves_user_edits_and_replacement_own(database):
    seed(database)
    database.execute(update(Project).where(Project.project_id == DEMO_PROJECT_ID).values(name="User renamed", is_active=False))
    database.execute(update(WatchTopic).where(WatchTopic.topic_id == demo_id("topic:ai")).values(topic_name="User topic", is_active=False))
    database.execute(update(WatchTerm).where(WatchTerm.term_id == demo_id("term:KEYWORD:chatgpt")).values(term="User term", normalized_term="custom", is_active=False))
    database.execute(update(SNSAccount).where(SNSAccount.account_id == demo_id("own:X")).values(account_name="renamed-own", is_active=False))
    database.execute(update(SNSAccount).where(SNSAccount.account_id == demo_id("competitor:1")).values(account_name="renamed-competitor"))
    add(database, SNSAccount, project_id=DEMO_PROJECT_ID, platform="X", account_name="user-active", account_role="OWN")
    add(database, Project, name="User project")
    database.commit()
    before = snapshot(database)
    seed(database)
    database.commit()
    assert snapshot(database) == before


def test_seed_preserves_inactive_renamed_own_without_reactivating(database):
    seed(database)
    database.execute(update(SNSAccount).where(SNSAccount.account_id == demo_id("own:X")).values(account_name="renamed", is_active=False))
    database.commit()
    before = snapshot(database)
    seed(database)
    database.commit()
    assert snapshot(database) == before
