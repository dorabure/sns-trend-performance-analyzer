import json
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import event, insert

from app.db.models import SNSPost, PostMetric, PostTopic, WatchTerm, TrendDaily
from app.services.my_account_service import MyAccountService
from app.services.trend_explorer_service import TrendExplorerService
from app.services.competitor_service import CompetitorService
from app.services.gap_analysis_service import GapAnalysisService
from app.services.overview_service import OverviewService
from app.providers.base import CsvDatasetType as D
from tests.imports.conftest import T1
from tests.providers.helpers import csv_text, row


def counted(engine, operation):
    statements = []
    def count(conn, cursor, statement, parameters, execution, many):
        if statement.lstrip().split()[0] in ('SELECT', 'WITH'): statements.append(statement)
    event.listen(engine, 'before_cursor_execute', count)
    try: result = operation()
    finally: event.remove(engine, 'before_cursor_execute', count)
    return result, len(statements)


@pytest.mark.parametrize('screen', ['own', 'ranking', 'popular', 'competitor', 'gap', 'overview', 'ai'])
def test_large_fixture_query_counts_and_response_bounds(context, postgres_engine, service, fake, screen):
    filters = MyAccountService.filters(date(2026, 10, 1), date(2026, 10, 3))
    own = MyAccountService(context.factory); trends = TrendExplorerService(context.factory)
    competitor = CompetitorService(context.factory); gap = GapAnalysisService(context.factory)
    overview = OverviewService(context.factory)
    operations = {'own': lambda: own.posts(context.project_id, filters, 2, 7, 'engagement', 'desc'),
        'ranking': lambda: trends.ranking(context.project_id, context.topic_id, filters, 7),
        'popular': lambda: trends.top_posts(context.project_id, context.topic_id, filters, 7),
        'competitor': lambda: competitor.top_posts(context.project_id, [context.competitor_id], filters, 7),
        'gap': lambda: gap.analysis(context.project_id, filters),
        'overview': lambda: overview.overview(context.project_id, filters),
        'ai': lambda: service.generate(context.project_id, filters)}
    before, before_count = counted(postgres_engine, operations[screen])
    if screen == 'ai': small_bytes = len(json.dumps(fake.calls[-1]))
    with context.factory() as session, session.begin():
        posts = [dict(post_id=uuid4(), project_id=context.project_id, platform='X', platform_post_id=f'quality-{role}-{i}',
            account_id=account, source_type=role, posted_at=T1, text='PRIVATE_TEXT' * 100, author_name='PRIVATE_AUTHOR')
            for role, account in [('OWN', context.own_id), ('MARKET', None), ('COMPETITOR', context.competitor_id)]
            for i in range(500)]
        session.execute(insert(SNSPost), posts)
        session.execute(insert(PostMetric), [dict(post_id=p['post_id'], recorded_at=T1, reach=10, likes=1) for p in posts])
        session.execute(insert(PostTopic), [dict(post_id=p['post_id'], topic_id=context.topic_id,
            match_type='MANUAL', match_score=100) for p in posts])
        terms = [dict(term_id=uuid4(), topic_id=context.topic_id, term=f'quality-{i}', normalized_term=f'quality-{i}', term_type='KEYWORD') for i in range(100)]
        session.execute(insert(WatchTerm), terms)
        session.execute(insert(TrendDaily), [dict(topic_id=context.topic_id, term_id=t['term_id'],
            platform='X', trend_date=date(2026, 10, 3), trend_score=80, window_days=7,
            post_count=10, engagement_count=10) for t in terms])
    after, after_count = counted(postgres_engine, operations[screen])
    assert after_count == before_count
    if screen in ['own', 'ranking', 'popular', 'competitor']:
        assert len(after.items) == 7
    if screen == 'own': assert after.total == 500 and after.page_size == 7
    if screen == 'overview':
        assert after.kpis.posts.value == 500 and len(after.top_trends) <= 5 and len(after.competitor_summary) <= 3
    if screen == 'ai':
        assert len(json.dumps(fake.calls[-1])) < small_bytes + 1500
        assert 'PRIVATE_TEXT' not in json.dumps(fake.calls[-1])
    print(f'QUALITY_PERFORMANCE {screen}: {before_count}/{after_count} SELECT/WITH; 1500 posts/100 terms')


@pytest.mark.parametrize('dataset', [D.OWN_POSTS, D.ACCOUNT_DAILY])
def test_import_query_structure_measured_without_semantic_rewrite(context, postgres_engine, tmp_path, dataset):
    counts = []
    for size in (10, 100):
        path = tmp_path / 'quality.csv'
        path.write_text(csv_text(dataset, [row(dataset, **({'post_id': f'import-{i}'} if dataset == D.OWN_POSTS else {})) for i in range(size)]), encoding='utf-8')
        def run():
            identifier, started = context.service.start(context.project_id, dataset, 'quality.csv')
            return context.service.run(identifier, started, context.project_id, dataset, path)
        result, count = counted(postgres_engine, run)
        assert result.status == 'SUCCESS' and result.success_count == size
        counts.append(count)
    if dataset == D.ACCOUNT_DAILY: assert counts[0] == counts[1]
    else:
        # Existing retained-match SELECT per post is measured, not hidden behind
        # an unsafe UPSERT/CSV last-wins rewrite. It is a documented bottleneck.
        assert counts[1] - counts[0] == 90
    print(f'QUALITY_PERFORMANCE import {dataset.value}: {counts} SELECT/WITH for 10/100 rows')
