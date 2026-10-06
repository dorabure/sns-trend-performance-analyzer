"""Explicit disposable browser fixture; never imported by production code.

Run only as python -m tests.quality.browser_fixture in a temporary container.
Uses real services, real PostgreSQL and CSV parsing, no external OpenAI calls.
"""
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from uuid import UUID

import uvicorn
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db.models import AIInsight, Project, ProjectPlatform, SNSAccount, SNSPost, PostMetric, WatchTopic, WatchTerm, TrendDaily
from app.services.insight_service import InsightService
from app.services.import_service import ImportService
from app.services.import_recovery import recover_interrupted_imports
from app.services.openai_insight_client import AIConfig, OpenAIInsightClient
from tests.quality.test_privacy_security import DEPENDENCIES
from app.services.settings_service import SettingsService
from app.services.my_account_service import MyAccountService
from app.services.trend_explorer_service import TrendExplorerService
from app.services.competitor_service import CompetitorService
from app.services.gap_analysis_service import GapAnalysisService
from app.services.overview_service import OverviewService
from tests.postgres_support import disposable_database, migrate
from tests.insights.conftest import content

PROJECT = UUID('00000000-0000-4000-8000-000000000113')
EMPTY = UUID('00000000-0000-4000-8000-000000000114')


class BrowserDelay:
    def __init__(self, application): self.application = application
    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] != 'GET' or 'platform=' not in scope.get('query_string', b'').decode():
            return await self.application(scope, receive, send)
        query = scope['query_string'].decode()
        print('QUALITY_BROWSER_REQUEST ' + json.dumps({'path': scope['path'], 'query': query}), flush=True)
        messages = []
        async def capture(message): messages.append(message)
        await self.application(scope, receive, capture)
        # Snapshot selected first, then held: old values must not overwrite new UI.
        await asyncio.sleep(6 if 'platform=INSTAGRAM' in query else 0.25)
        for message in messages: await send(message)
        print('QUALITY_BROWSER_COMPLETED ' + json.dumps({'path': scope['path'], 'query': query}), flush=True)


@asynccontextmanager
async def lifespan(application):
    with disposable_database() as engine:
        migrate(engine, 'upgrade', 'head'); factory = sessionmaker(engine, expire_on_commit=False)
        with factory() as session, session.begin():
            session.add_all([Project(project_id=PROJECT, name='Phase13 Browser Fixture'),
                             Project(project_id=EMPTY, name='Phase13 Empty X')]); session.flush()
            for pid, platforms in [(PROJECT, ['X', 'INSTAGRAM']), (EMPTY, ['X'])]:
                topic = WatchTopic(project_id=pid, topic_name='架空検証Topic'); session.add(topic); session.flush()
                term = WatchTerm(topic_id=topic.topic_id, term='quality', normalized_term='quality', term_type='KEYWORD')
                session.add(term); session.flush()
                for platform in platforms:
                    session.add(ProjectPlatform(project_id=pid, platform=platform))
                    for role in ['OWN', 'COMPETITOR']:
                        account = SNSAccount(project_id=pid, platform=platform, account_role=role,
                            account_name=f'quality_{role.lower()}_{platform.lower()}')
                        session.add(account); session.flush()
                        if pid == PROJECT:
                            post = SNSPost(project_id=pid, account_id=account.account_id, platform=platform,
                                source_type=role, platform_post_id=f'quality-{role}', text='架空ブラウザー検証データ',
                                posted_at=datetime(2026, 10, 2, 1, tzinfo=timezone.utc))
                            session.add(post); session.flush()
                            session.add(PostMetric(post_id=post.post_id, recorded_at=datetime.now(timezone.utc),
                                reach=10 if platform == 'X' else 90, likes=1))
                    if pid == PROJECT:
                        session.add(TrendDaily(topic_id=topic.topic_id, term_id=term.term_id, platform=platform,
                            trend_date=date(2026, 10, 2), trend_score=80, post_count=10, engagement_count=1))
            # A distinctive saved fixture makes stale AI responses observable.
            # This is synthetic evidence, never a live generation or production row.
            session.add(AIInsight(project_id=PROJECT, platform='INSTAGRAM',
                analysis_from=date(2026, 9, 30), analysis_to=date(2026, 10, 3),
                content=content('旧Projectの架空Instagramレポート。実OpenAI生成ではありません。').model_dump(mode='json'),
                evidence={'kpis': [{'id': 'KPI_REACH', 'label': 'Fixture Reach', 'values': {'value': 90}}],
                    'trends': [], 'competitors': [], 'opportunities': []},
                input_summary={'fixture_only': True}, model_name='fixture-no-external-api', prompt_version='phase12-v1'))
        services = [SettingsService(factory), ImportService(factory), MyAccountService(factory),
            TrendExplorerService(factory), CompetitorService(factory), GapAnalysisService(factory),
            OverviewService(factory), InsightService(factory, OpenAIInsightClient(AIConfig()))]
        for dependency, service in zip(DEPENDENCIES, services):
            def provide(value):
                def override(): return value
                return override
            app.dependency_overrides[dependency] = provide(service)
        recover_interrupted_imports(factory)
        print('PHASE13_BROWSER_READY', flush=True)
        try: yield
        finally: app.dependency_overrides.clear()


if __name__ == '__main__':
    app.router.lifespan_context = lifespan
    uvicorn.run(BrowserDelay(app), host='0.0.0.0', port=8000)
