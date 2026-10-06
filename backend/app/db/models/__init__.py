"""Import every model so Alembic sees all business tables."""

from app.db.models.account import AccountMetric, SNSAccount
from app.db.models.ai_insight import AIInsight
from app.db.models.import_history import ImportHistory
from app.db.models.job import JobRun, JobStep
from app.db.models.job_schedule import JobSchedule
from app.db.models.post import PostMetric, SNSPost
from app.db.models.project import Project, ProjectPlatform
from app.db.models.provider import ProviderConnection, ProviderSyncState
from app.db.models.topic import PostTerm, PostTopic, WatchTerm, WatchTopic
from app.db.models.trend import TrendDaily

__all__ = [
    "AccountMetric", "SNSAccount", "AIInsight", "ImportHistory", "PostMetric", "SNSPost",
    "Project", "ProjectPlatform", "PostTerm", "PostTopic", "WatchTerm", "WatchTopic", "TrendDaily",
    "ProviderConnection", "ProviderSyncState",
    "JobRun", "JobStep", "JobSchedule",
]
