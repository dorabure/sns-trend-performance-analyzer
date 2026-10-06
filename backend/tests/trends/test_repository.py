from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import event, select

from app.db.models import PostMetric, PostTerm, PostTopic, Project, SNSPost, TrendDaily
from app.repositories.trend_repository import TrendRepository


def test_latest_metrics_left_join_and_scoped_links(context):
    with context.factory() as session, session.begin():
        facts = []
        for source in ("MARKET", "MARKET", "OWN", "COMPETITOR"):
            post = SNSPost(project_id=context.project_id, platform="X", platform_post_id=str(uuid4()),
                           source_type=source, posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
            session.add(post)
            session.flush()
            facts.append(post)
            session.add(PostTopic(post_id=post.post_id, topic_id=context.topic_id, match_type="MANUAL"))
            session.add(PostTerm(post_id=post.post_id, term_id=context.terms["AI"], match_method="AI"))
        session.add_all([PostMetric(post_id=facts[0].post_id, recorded_at=datetime(2026, 1, 1, tzinfo=timezone.utc), likes=10),
                         PostMetric(post_id=facts[0].post_id, recorded_at=datetime(2026, 1, 2, tzinfo=timezone.utc), likes=30)])
    with context.factory() as session:
        inputs = TrendRepository().load(session, context.project_id)
    by_id = {post.post_id: post for post in inputs.posts}
    assert set(by_id) == {facts[0].post_id, facts[1].post_id}
    assert by_id[facts[0].post_id].likes == 30
    assert by_id[facts[1].post_id].likes is None
    assert len(inputs.topic_links) == len(inputs.term_links) == 2
    assert inputs.platforms == ["X"] and inputs.topics == [context.topic_id]
    assert len(inputs.terms) == 5


def test_latest_query_count_independent_of_post_count(context):
    def read_queries():
        statements = []
        with context.factory() as session:
            connection = session.connection()
            def collect(conn, cursor, statement, parameters, current, executemany):
                statements.append(statement)
            event.listen(connection, "before_cursor_execute", collect)
            TrendRepository().load(session, context.project_id)
        return statements
    empty_count = len(read_queries())
    with context.factory() as session, session.begin():
        posts = [SNSPost(project_id=context.project_id, platform="X", platform_post_id=f"bulk-{i}",
                         source_type="MARKET", posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc)) for i in range(100)]
        session.add_all(posts)
        session.flush()
        session.add_all([PostMetric(post_id=post.post_id, recorded_at=datetime(2026, 1, 1, tzinfo=timezone.utc), likes=10)
                         for post in posts])
    queries = read_queries()
    assert len(queries) == empty_count == 6
    latest_queries = [statement.lower() for statement in queries if "join lateral" in statement.lower()]
    assert len(latest_queries) == 1
    assert "post_metrics.post_id = sns_posts.post_id" in latest_queries[0]
    assert "order by post_metrics.recorded_at desc" in latest_queries[0]
    assert "limit" in latest_queries[0]


def test_replace_deletes_inactive_project_rows_only(context):
    with context.factory() as session, session.begin():
        other = Project(name="other")
        session.add(other)
        session.flush()
        from app.db.models import WatchTopic
        other_topic = WatchTopic(project_id=other.project_id, topic_name="AI")
        session.add(other_topic)
        session.flush()
        inactive_id = session.scalar(select(WatchTopic.topic_id).where(
            WatchTopic.project_id == context.project_id, WatchTopic.is_active.is_(False)))
        session.add_all([TrendDaily(topic_id=inactive_id, platform="X", trend_date=datetime(2026, 1, 1).date()),
                         TrendDaily(topic_id=other_topic.topic_id, platform="X", trend_date=datetime(2026, 1, 1).date())])
    try:
        with context.factory() as session, session.begin():
            TrendRepository().replace(session, context.project_id, [])
        with context.factory() as session:
            remaining = list(session.scalars(select(TrendDaily)))
            assert len(remaining) == 1 and remaining[0].topic_id == other_topic.topic_id
    finally:
        from sqlalchemy import delete
        with context.factory() as session, session.begin():
            session.execute(delete(Project).where(Project.project_id == other.project_id))
