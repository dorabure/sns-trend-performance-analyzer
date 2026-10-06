"""Explicit, additive demo configuration seed. Never invoked on API startup."""
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Project, ProjectPlatform, SNSAccount, WatchTerm, WatchTopic

DEMO_PROJECT_ID = uuid.UUID("773a5972-5f3d-5e49-87ed-40f7d0d26029")
DEMO_PROJECT_NAME = "Demo SNS Analysis Project"


def demo_id(label: str) -> uuid.UUID:
    return uuid.uuid5(DEMO_PROJECT_ID, label)


def insert_missing(session: Session, model, values: dict) -> None:
    # Either the stable primary key or a natural key may already exist after edits.
    session.execute(insert(model).values(**values).on_conflict_do_nothing())


def seed(session: Session) -> None:
    # Stable UUID identifies seed-owned project; display name may be changed by users.
    insert_missing(session, Project, {
        "project_id": DEMO_PROJECT_ID, "name": DEMO_PROJECT_NAME,
        "description": "架空のSNS分析デモ。実在の企業・アカウントとは関係ありません。",
    })
    # Serialize simultaneous seed runs without resetting existing configuration.
    session.execute(select(Project).where(Project.project_id == DEMO_PROJECT_ID).with_for_update())

    for platform in ("X", "INSTAGRAM"):
        insert_missing(session, ProjectPlatform, {
            "project_platform_id": demo_id(f"platform:{platform}"),
            "project_id": DEMO_PROJECT_ID, "platform": platform,
        })
        account_name = f"dummy_demo_own_{platform.lower()}"
        existing_active = session.scalar(select(SNSAccount.account_id).where(
            SNSAccount.project_id == DEMO_PROJECT_ID, SNSAccount.platform == platform,
            SNSAccount.account_role == "OWN", SNSAccount.is_active.is_(True),
        ))
        if existing_active is None:
            insert_missing(session, SNSAccount, {
                "account_id": demo_id(f"own:{platform}"), "project_id": DEMO_PROJECT_ID,
                "platform": platform, "account_name": account_name,
                "display_name": f"Dummy Demo OWN ({platform})", "account_role": "OWN",
            })

    for number, platform in ((1, "X"), (2, "X"), (3, "INSTAGRAM")):
        insert_missing(session, SNSAccount, {
            "account_id": demo_id(f"competitor:{number}"), "project_id": DEMO_PROJECT_ID,
            "platform": platform, "account_name": f"dummy_demo_competitor_{number}",
            "display_name": f"Dummy Demo Competitor {number}", "account_role": "COMPETITOR",
        })

    for label, name in (("ai", "生成AI"), ("productivity", "業務効率化")):
        insert_missing(session, WatchTopic, {
            "topic_id": demo_id(f"topic:{label}"), "project_id": DEMO_PROJECT_ID, "topic_name": name,
        })

    # Explicit normalized values; a general Normalizer belongs to a later phase.
    topic = session.get(WatchTopic, demo_id("topic:ai"))
    if topic is None:
        topic = session.scalar(select(WatchTopic).where(
            WatchTopic.project_id == DEMO_PROJECT_ID, WatchTopic.topic_name == "生成AI",
        ))
    for term, normalized, term_type in (
        ("ChatGPT", "chatgpt", "KEYWORD"), ("Claude", "claude", "KEYWORD"),
        ("Gemini", "gemini", "KEYWORD"), ("AIエージェント", "aiエージェント", "KEYWORD"),
        ("#生成AI", "#生成ai", "HASHTAG"), ("#ChatGPT", "#chatgpt", "HASHTAG"),
    ):
        insert_missing(session, WatchTerm, {
            "term_id": demo_id(f"term:{term_type}:{normalized}"), "topic_id": topic.topic_id,
            "term": term, "normalized_term": normalized, "term_type": term_type,
        })


def main() -> None:
    from app.db.session import SessionLocal

    with SessionLocal.begin() as session:
        seed(session)
    print("Demo configuration seed completed (existing rows preserved).")


if __name__ == "__main__":
    main()
