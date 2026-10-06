"""Rebuild existing posts using the same persistence path as CSV imports."""
from sqlalchemy import select

from app.db.models import SNSPost, WatchTerm, WatchTopic
from app.dto.normalized import NormalizedPost, Platform, SourceType
from app.services.matching_service import TermCandidate
from app.repositories.import_repository import ImportRepository
from app.services.trend_service import TrendService


class RematchService:
    def __init__(self, repository=None, trend_service=None):
        self.repository = repository or ImportRepository()
        self.trend_service = trend_service or TrendService()

    def refresh_project(self, session, project_id):
        session.flush()
        terms = session.scalars(select(WatchTerm).join(WatchTopic).where(
            WatchTopic.project_id == project_id, WatchTopic.is_active.is_(True),
            WatchTerm.is_active.is_(True))).all()
        candidates = [TermCandidate(t.term_id, t.topic_id, t.term, t.normalized_term, t.term_type) for t in terms]
        # One streamed query; matching persistence preloads retained links per batch.
        posts = session.scalars(select(SNSPost).where(SNSPost.project_id == project_id)
                                .order_by(SNSPost.post_id).execution_options(yield_per=500))
        batch = []
        for post in posts:
            keyword = (post.raw_data or {}).get("keyword")
            keywords = [keyword.strip()] if isinstance(keyword, str) and keyword.strip() else []
            dto = NormalizedPost(source_type=SourceType(post.source_type), platform=Platform(post.platform),
                                 platform_post_id=post.platform_post_id, posted_at=post.posted_at,
                                 text=post.text, hashtags=post.hashtags or [], keywords=keywords)
            batch.append((post.post_id, dto))
            if len(batch) == 500:
                self.repository.rebuild_matches_batch(session, batch, candidates)
                batch = []
        if batch:
            self.repository.rebuild_matches_batch(session, batch, candidates)
        self.trend_service.rebuild_project(session, project_id)
