"""Explicit test-only browser server. Never imported by app.main or production routes.

Run with `python -m tests.insights.browser_fixture` in a temporary backend container.
The real application DB is untouched. Normal shutdown drops the validated disposable DB.
"""
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from time import sleep
from uuid import UUID

import uvicorn
from sqlalchemy.orm import sessionmaker

from app.api.v1.insights import get_insight_service
from app.api.v1.overview import get_overview_service
from app.api.v1.settings import get_settings_service
from app.db.models import Project, ProjectPlatform, SNSAccount, SNSPost, PostMetric, TrendDaily, WatchTopic
from app.main import app
from app.services.insight_service import InsightService
from app.services.overview_service import OverviewService
from app.services.settings_service import SettingsService
from app.services.openai_insight_client import failure
from tests.insights.conftest import FakeClient, content
from tests.postgres_support import disposable_database, migrate

PROJECT = UUID('00000000-0000-4000-8000-000000000012')
EMPTY = UUID('00000000-0000-4000-8000-000000000013')


class BrowserClient(FakeClient):
    def generate(self, summary, evidence):
        sleep(4)
        self.calls.append((summary,evidence))
        if len(self.calls)%3==0:
            raise failure('AI_TIMEOUT','AI分析がタイムアウトしました。再試行してください。')
        return content(f'ブラウザ検証用の架空レポート {len(self.calls)}。実OpenAI生成ではありません。'), 'browser-fake-model'


class BrowserService(InsightService):
    def latest(self, project_id, filters):
        # Deliberately reorder responses to exercise the frontend version guard.
        sleep(6 if filters.platform=='INSTAGRAM' else 0.5)
        return super().latest(project_id,filters)


@asynccontextmanager
async def lifespan(application):
    with disposable_database() as engine:
        migrate(engine,'upgrade','head')
        factory=sessionmaker(engine,expire_on_commit=False)
        with factory() as s,s.begin():
            s.add_all([Project(project_id=PROJECT,name='Phase12 Browser Fake'),Project(project_id=EMPTY,name='Phase12 Empty X')]);s.flush()
            s.add_all([ProjectPlatform(project_id=PROJECT,platform='X'),ProjectPlatform(project_id=PROJECT,platform='INSTAGRAM'),ProjectPlatform(project_id=EMPTY,platform='X')])
            for sns in ('X','INSTAGRAM'):
                account=SNSAccount(project_id=PROJECT,platform=sns,account_name=f'fake_own_{sns}',account_role='OWN');s.add(account);s.flush()
                post=SNSPost(project_id=PROJECT,account_id=account.account_id,source_type='OWN',platform=sns,
                    platform_post_id='browser-fixture',posted_at=datetime(2026,10,3,1,tzinfo=timezone.utc),text='Not sent to AI')
                s.add(post);s.flush();s.add(PostMetric(post_id=post.post_id,recorded_at=datetime.now(timezone.utc),reach=0,likes=0))
            topic=WatchTopic(project_id=PROJECT,topic_name='架空Topic');s.add(topic);s.flush()
            s.add(TrendDaily(topic_id=topic.topic_id,platform='X',trend_date=date(2026,10,3),trend_score=80,post_count=100))
        fake=BrowserClient()
        app.dependency_overrides[get_insight_service]=lambda: BrowserService(factory,fake)
        app.dependency_overrides[get_settings_service]=lambda: SettingsService(factory)
        app.dependency_overrides[get_overview_service]=lambda: OverviewService(factory)
        print('PHASE12_BROWSER_FAKE_READY',flush=True)
        try: yield
        finally: app.dependency_overrides.clear()


if __name__=='__main__':
    app.router.lifespan_context=lifespan
    uvicorn.run(app,host='0.0.0.0',port=8000)
