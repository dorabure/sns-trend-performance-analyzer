from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import AccountMetric, PostMetric, PostTerm, PostTopic, SNSPost, WatchTerm
from app.dto.normalized import NormalizedAccountMetric, NormalizedPost
from app.services.matching_service import TermCandidate, match_post

POST_METRICS = ("impressions", "reach", "views", "likes", "comments", "shares", "saves")


class ImportRepository:
    """No commits here: one CSV's writes share the service transaction."""

    def save_account_metric(self, session: Session, account_id: UUID, record: NormalizedAccountMetric,
                            *, ingest_key=None, ingest_job_run_id=None) -> None:
        values = {name: getattr(record, name) for name in ("followers", "following", "post_count")}
        values["raw_metrics"] = record.raw_metrics
        if ingest_key is not None:
            values.update(ingest_key=ingest_key, ingest_job_run_id=ingest_job_run_id)
        statement = insert(AccountMetric).values(account_id=account_id, recorded_date=record.recorded_date, **values)
        session.execute(statement.on_conflict_do_update(
            constraint="uq_account_metrics_account_date", set_=values))

    def save_followers(self, session: Session, account_id: UUID, post: NormalizedPost, followers: int) -> None:
        # Original timezone date, and CSV order's last provided value wins (DB design §26).
        statement = insert(AccountMetric).values(
            account_id=account_id, recorded_date=post.posted_at.date(), followers=followers,
            raw_metrics={"followers": followers})
        session.execute(statement.on_conflict_do_update(
            constraint="uq_account_metrics_account_date",
            set_={"followers": followers,
                  "raw_metrics": AccountMetric.raw_metrics.op("||")({"followers": followers})}))

    def save_post(self, session: Session, project_id: UUID, account_id: UUID | None,
                  post: NormalizedPost, recorded_at: datetime, candidates: list[TermCandidate],
                  *, data_origin='DEMO_CSV', provider_connection_id=None, ingest_key=None, ingest_job_run_id=None) -> UUID:
        values = dict(account_id=account_id, source_type=post.source_type.value,
                      author_name=post.account_name if account_id else None, posted_at=post.posted_at,
                      text=post.text, media_type=post.media_type.value if post.media_type else None,
                      permalink=post.permalink, hashtags=post.hashtags, raw_data=post.raw_data)
        if provider_connection_id is not None:
            values.update(data_origin=data_origin, provider_connection_id=provider_connection_id)
        statement = insert(SNSPost).values(project_id=project_id, platform=post.platform.value,
                                          platform_post_id=post.platform_post_id, **values)
        post_id = session.execute(statement.on_conflict_do_update(
            constraint="uq_sns_posts_project_platform_post",
            set_={**values, "updated_at": func.current_timestamp()}).returning(SNSPost.post_id)).scalar_one()
        metrics = {name: getattr(post, name) for name in POST_METRICS}
        if ingest_key is not None:
            metrics.update(ingest_key=ingest_key, ingest_job_run_id=ingest_job_run_id)
        raw_metrics = {name: getattr(post, name) for name in POST_METRICS}
        statement = insert(PostMetric).values(post_id=post_id, recorded_at=recorded_at,
                                            **metrics, raw_metrics=raw_metrics)
        session.execute(statement.on_conflict_do_update(
            constraint="uq_post_metrics_post_recorded", set_={**metrics, "raw_metrics": raw_metrics}))
        self.rebuild_matches(session, post_id, post, candidates)
        return post_id

    def rebuild_matches(self, session: Session, post_id: UUID, post: NormalizedPost,
                        candidates: list[TermCandidate]) -> None:
        self.rebuild_matches_batch(session, [(post_id, post)], candidates)

    def rebuild_matches_batch(self, session: Session, posts: list[tuple[UUID, NormalizedPost]],
                              candidates: list[TermCandidate]) -> None:
        ids = [post_id for post_id, _ in posts]
        if not ids:
            return
        session.execute(delete(PostTerm).where(PostTerm.post_id.in_(ids),
                                              PostTerm.match_method.in_(("EXACT", "NORMALIZED"))))
        session.execute(delete(PostTopic).where(PostTopic.post_id.in_(ids),
                                               PostTopic.match_type.in_(("KEYWORD", "HASHTAG"))))
        retained = session.execute(select(PostTerm.post_id, WatchTerm.topic_id, WatchTerm.term_type).join(
            WatchTerm, PostTerm.term_id == WatchTerm.term_id).where(PostTerm.post_id.in_(ids))).all()
        parents = {}
        for post_id, topic_id, term_type in retained:
            parents.setdefault(post_id, []).append((topic_id, term_type))
        term_rows, topic_rows = [], []
        for post_id, post in posts:
            matches = match_post(post, candidates)
            term_rows.extend(dict(post_id=post_id, term_id=term_id, match_method=method, match_score=100)
                             for term_id, method in matches.terms.items())
            # Preserve the parent relationship of MANUAL/AI terms, including inactive terms.
            for topic_id, term_type in parents.get(post_id, []):
                if term_type == "HASHTAG" or topic_id not in matches.topics:
                    matches.topics[topic_id] = term_type
            topic_rows.extend(dict(post_id=post_id, topic_id=topic_id, match_type=kind, match_score=100)
                              for topic_id, kind in matches.topics.items())
        # Bound statement parameters even for many matches per post.
        for model, rows, keys in [(PostTerm, term_rows, ["post_id", "term_id"]),
                                  (PostTopic, topic_rows, ["post_id", "topic_id"])]:
            for start in range(0, len(rows), 1000):
                session.execute(insert(model).values(rows[start:start + 1000])
                                .on_conflict_do_nothing(index_elements=keys))
