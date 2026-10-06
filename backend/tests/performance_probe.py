"""Phase12 standalone probe: disposable databases only, no external HTTP.

Run from /app: python -m tests.performance_probe before /tmp/phase12_before.json
One warmup and five sequential samples; EXPLAIN runs outside timed samples.
Canonical source is read-only DEMO, and only analytics tables are copied.
"""
import hashlib
import json
import statistics
import resource
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import httpx
from sqlalchemy import delete, event, insert, select, text
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import (AIInsight, PostMetric, PostTopic, Project, ProjectPlatform,
                           SNSAccount, SNSPost, TrendDaily, WatchTerm, WatchTopic)
from app.db.session import engine as source_engine
from app.services.my_account_service import MyAccountService
from app.services.overview_service import OverviewService
from app.services.competitor_service import CompetitorService
from app.services.gap_analysis_service import GapAnalysisService
from app.services.trend_explorer_service import TrendExplorerService
from app.services.trend_service import TrendService
from app.services.insight_service import InsightService
from app.services.insight_history_service import InsightHistoryService
from tests.insights.conftest import FakeClient, content
from tests.postgres_support import disposable_database, migrate

NOW = datetime(2026, 10, 3, 1, tzinfo=timezone.utc)


def blocked(*args, **kwargs):
    raise AssertionError('External HTTP is forbidden in performance probes')


def encoded(value):
    if hasattr(value, 'model_dump'):
        value = value.model_dump(mode='json', by_alias=True)
    return json.dumps(value, default=str, sort_keys=True, ensure_ascii=False).encode()


def probe(engine, label, operation, output, plans):
    operation()  # warmup is explicitly excluded
    samples, counts, sql_times, row_counts = [], [], [], []
    captured = []
    def before(conn, cursor, statement, params, context, many):
        context._probe_started = time.perf_counter()
    def after(conn, cursor, statement, params, context, many):
        if statement.lstrip().upper().startswith(('SELECT', 'WITH')):
            captured.append((statement, params, (time.perf_counter() - context._probe_started) * 1000, cursor.rowcount))
    event.listen(engine, 'before_cursor_execute', before)
    event.listen(engine, 'after_cursor_execute', after)
    try:
        for _ in range(5):
            captured.clear()
            started = time.perf_counter()
            result = operation()
            elapsed = (time.perf_counter() - started) * 1000
            samples.append(elapsed)
            counts.append(len(captured))
            sql_times.append(sum(q[2] for q in captured))
            row_counts.append(sum(max(0, q[3]) for q in captured))
        queries = list(captured)
    finally:
        event.remove(engine, 'before_cursor_execute', before)
        event.remove(engine, 'after_cursor_execute', after)
    started = time.perf_counter()
    raw = encoded(result)
    serialization = (time.perf_counter() - started) * 1000
    # Generate inserts fresh identity/time, but the content/input/evidence must match.
    golden = json.loads(raw)
    if label.endswith('ai_generate'):
        golden.pop('insight_id', None)
        golden.pop('generated_at', None)
    output[label] = dict(runs_ms=samples, min_ms=min(samples), median_ms=statistics.median(samples),
        max_ms=max(samples), query_counts=counts, sql_ms=sql_times, rows_fetched=row_counts,
        process_high_water_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        serialization_ms=serialization, response_bytes=len(raw),
        golden_sha256=hashlib.sha256(encoded(golden)).hexdigest())
    Path(sys.argv[2] + '.partial.json').write_text(json.dumps(output, ensure_ascii=False, indent=2))
    seen = set()
    for statement, params, _, _ in queries:
        if statement in seen:
            continue
        seen.add(statement)
        with engine.connect() as connection:
            plan = connection.exec_driver_sql('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + statement, params).scalar()
        plans.append(dict(operation=label, sql=statement, plan=plan))
    print(label, round(statistics.median(samples), 2), 'ms', flush=True)


def analyze(engine):
    with engine.begin() as connection:
        connection.execute(text('ANALYZE'))


def canonical(engine):
    # Exclude all credentials, providers, jobs, import history and private data.
    allowed = {'projects', 'project_platforms', 'sns_accounts', 'watch_topics', 'watch_terms',
        'sns_posts', 'post_metrics', 'account_metrics', 'post_topics', 'post_terms',
        'trend_daily', 'ai_insights'}
    with source_engine.connect().execution_options(postgresql_readonly=True) as source:
        project = source.execute(select(Project.__table__).where(Project.name == 'Phase14 Canonical Demo')).mappings().one()
        assert project['data_mode'] == 'DEMO'
        pid = project['project_id']
        # The normal DB is entirely fictional; assert no LIVE projects before copying.
        assert not source.scalar(select(Project.project_id).where(Project.data_mode == 'LIVE').limit(1))
        with engine.begin() as destination:
            for table in Base.metadata.sorted_tables:
                if table.name in allowed:
                    rows = [dict(r) for r in source.execute(select(table)).mappings()]
                    if rows:
                        destination.execute(insert(table), rows)
    return pid


def large_fixture(engine, size, all_roles=False):
    pid, own, competitor, topic = [UUID(int=n) for n in (100, 101, 102, 103)]
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as s, s.begin():
        s.add(Project(project_id=pid, name='Phase12 fictional performance only'))
        s.flush()
        s.add(ProjectPlatform(project_platform_id=UUID(int=104), project_id=pid, platform='X'))
        s.add_all([SNSAccount(account_id=aid, project_id=pid, platform='X', account_name=name, account_role=role)
            for aid, name, role in [(own, 'fixture_own', 'OWN'), (competitor, 'fixture_competitor', 'COMPETITOR')]])
        s.add(WatchTopic(topic_id=topic, project_id=pid, topic_name='fixture'))
        s.flush()
        roles = [('OWN', own), ('MARKET', None), ('COMPETITOR', competitor)] if all_roles else [('OWN', own)]
        posts = [dict(post_id=UUID(int=10000 + ri * 10000 + i), project_id=pid,
            account_id=aid, platform='X', source_type=role, platform_post_id=f'{role}-{i}',
            posted_at=NOW + timedelta(minutes=i % 120), text='FICTIONAL_TEXT' * 100,
            hashtags=['fixture'], media_type='TEXT')
            for ri, (role, aid) in enumerate(roles) for i in range(size)]
        s.execute(insert(SNSPost), posts)
        s.execute(insert(PostMetric), [dict(post_metric_id=UUID(int=100000 + i), post_id=p['post_id'],
            recorded_at=NOW, reach=100 if i % 3 else None, impressions=200,
            likes=i % 11, comments=None if i % 7 else 0) for i, p in enumerate(posts)])
        s.execute(insert(PostTopic), [dict(post_id=p['post_id'], topic_id=topic,
            match_type='MANUAL', match_score=100) for p in posts])
        terms = [dict(term_id=UUID(int=200000+i), topic_id=topic, term=f'fixture-{i}',
            normalized_term=f'fixture-{i}', term_type='KEYWORD') for i in range(100)]
        s.execute(insert(WatchTerm), terms)
        s.execute(insert(TrendDaily), [dict(topic_id=topic, term_id=t['term_id'], platform='X',
            trend_date=date(2026, 10, 3), window_days=7, trend_score=80,
            post_count=10, engagement_count=10) for t in terms])
    return pid, competitor, topic


def operations(engine, pid, competitor, topic, filters, prefix, output, plans):
    factory = sessionmaker(engine, expire_on_commit=False)
    own, overview = MyAccountService(factory), OverviewService(factory)
    comp, gap, trend = CompetitorService(factory), GapAnalysisService(factory), TrendExplorerService(factory)
    with factory() as s:
        post_id = s.scalar(select(SNSPost.post_id).where(SNSPost.project_id == pid, SNSPost.source_type == 'OWN').order_by(SNSPost.post_id))
    for name, operation in [
        ('own_analytics', lambda: own.analytics(pid, filters)),
        ('own_list', lambda: own.posts(pid, filters, 1, 10, 'posted_at', 'desc')),
        ('own_detail', lambda: own.detail(pid, post_id, filters)),
        ('overview', lambda: overview.overview(pid, filters)),
        ('competitor', lambda: comp.analytics(pid, competitor, filters)),
        ('competitor_top', lambda: comp.top_posts(pid, competitor, filters, 10)),
        ('gap', lambda: gap.analysis(pid, filters)),
        ('ranking', lambda: trend.ranking(pid, topic, filters, 10)),
        ('trend_top', lambda: trend.top_posts(pid, topic, filters, 10)),
    ]:
        probe(engine, prefix + name, operation, output, plans)
    fake = FakeClient()
    ai = InsightService(factory, fake)
    probe(engine, prefix + 'ai_generate', lambda: ai.generate(pid, filters), output, plans)
    output[prefix + 'ai_generate']['external_input_bytes'] = len(encoded(fake.calls[-1]))
    output[prefix + 'ai_generate']['external_input_sha256'] = hashlib.sha256(encoded(fake.calls[-1])).hexdigest()
    def rebuild():
        with factory() as s, s.begin():
            return TrendService().rebuild_project(s, pid)
    probe(engine, prefix + 'rebuild', rebuild, output, plans)


def main():
    httpx.HTTPTransport.handle_request = blocked
    httpx.AsyncHTTPTransport.handle_async_request = blocked
    stage, path = sys.argv[1:3]
    output, plans = {}, []
    with disposable_database() as engine:
        migrate(engine, 'upgrade', 'head')
        pid = canonical(engine)
        analyze(engine)
        factory = sessionmaker(engine)
        with factory() as s:
            comps = list(s.scalars(select(SNSAccount.account_id).where(SNSAccount.project_id == pid, SNSAccount.account_role == 'COMPETITOR')))
            topic = s.scalar(select(WatchTopic.topic_id).where(WatchTopic.project_id == pid).order_by(WatchTopic.topic_id))
        operations(engine, pid, comps, topic, MyAccountService.filters(date(2026,7,7), date(2026,10,4)), 'canonical_', output, plans)
    for size, roles in [(100, False), (1000, False), (2000, False), (500, True)]:
        with disposable_database() as engine:
            migrate(engine, 'upgrade', 'head')
            pid, comp, topic = large_fixture(engine, size, roles)
            analyze(engine)
            operations(engine, pid, [comp], topic, MyAccountService.filters(date(2026,10,1), date(2026,10,3)),
                f'{"quality1500" if roles else "own"+str(size)}_', output, plans)
            if roles:
                factory = sessionmaker(engine, expire_on_commit=False)
                history = InsightHistoryService(factory)
                for count in [100, 1000, 5000]:
                    with factory() as s, s.begin():
                        s.execute(delete(AIInsight))
                        s.execute(insert(AIInsight), [dict(insight_id=UUID(int=300000+i), project_id=pid,
                            platform='X', analysis_from=date(2026,10,1), analysis_to=date(2026,10,3),
                            created_at=NOW + timedelta(seconds=i), content=content().model_dump(mode='json'),
                            evidence=dict(kpis=[], trends=[], competitors=[], opportunities=[]),
                            input_summary={'fixture': 0, 'unknown': None}, model_name='fake', prompt_version='fixture') for i in range(count)])
                    analyze(engine)
                    page = history.history(pid, limit=10)
                    iid = page.items[0].insight_id
                    for name, op in [('first', lambda: history.history(pid, limit=10)),
                        ('next', lambda: history.history(pid, limit=10, cursor=page.next_cursor)),
                        ('detail', lambda: history.detail(pid, iid)), ('compare', lambda: history.compare_previous(pid, iid))]:
                        probe(engine, f'history{count}_{name}', op, output, plans)
    result = dict(stage=stage, timestamp=datetime.now(timezone.utc).isoformat(), warmup=1,
        measured_runs=5, statement_timeout_ms=120000, external_http_calls=0,
        statistics_analyzed=True, operations=output)
    Path(path).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    Path(path + '.plans.json').write_text(json.dumps(plans, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
