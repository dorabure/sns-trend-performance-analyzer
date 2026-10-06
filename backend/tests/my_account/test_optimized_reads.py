from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import event

from app.schemas.my_account import PostPage
from tests.my_account.test_api import START, END, add_post
from tests.imports.conftest import T1


@pytest.mark.parametrize('order', ['asc', 'desc'])
@pytest.mark.parametrize('page', [1, 2, 4, 9])
def test_timestamp_sql_page_equals_full_response_with_ties_missing_and_latest_metrics(context, service, order, page):
    for i in range(7):
        add_post(context, post_id=UUID(int=i+1), posted_at=T1 + timedelta(hours=i//3),
            snapshots=[{'reach':100, 'likes':1}, {'reach':None, 'likes':0}] if i % 2 else None)
    filters = service.filters(START, END)
    with service.read(context.project_id) as s:
        items, _ = service.load(s, context.project_id, filters)
    expected = PostPage(items=service.repository.paginate(items, page, 2, 'posted_at', order),
        total=7, page=page, page_size=2)
    assert service.posts(context.project_id, filters, page, 2, 'posted_at', order).model_dump() == expected.model_dump()


def test_default_page_fetches_only_page_rows_and_keeps_three_queries(context, service, postgres_engine):
    for i in range(30):
        add_post(context, metrics={'reach':100, 'likes':i})
    selected = []
    def after(conn, cursor, statement, params, execution, many):
        if statement.lstrip().upper().startswith(('SELECT', 'WITH')):
            selected.append((statement, cursor.rowcount))
    event.listen(postgres_engine, 'after_cursor_execute', after)
    try:
        result = service.posts(context.project_id, service.filters(START, END), 2, 3, 'posted_at', 'desc')
    finally:
        event.remove(postgres_engine, 'after_cursor_execute', after)
    assert result.total == 30 and len(result.items) == 3
    assert len(selected) == 3
    assert selected[-1][1] == 3


@pytest.mark.parametrize('keyword,hashtag', [(None,None), ('ＣｈａｔＧＰＴ',None), (None,'#生成AI')])
def test_lean_analytics_matches_full_facts_for_unicode_null_zero_and_mixed_cohorts(context, service, keyword, hashtag):
    for metrics in [None, {'reach':0,'likes':0}, {'reach':100,'likes':10}, {'impressions':100,'likes':20}]:
        add_post(context, metrics=metrics)
    filters = service.filters(START, END, keyword=keyword, hashtag=hashtag)
    with service.read(context.project_id) as s:
        full, _ = service.load(s, context.project_id, filters)
        lean, _ = service.load(s, context.project_id, filters, analytics=True)
    assert service.analytics_from_items(lean, service.kpis(lean, []), filters).model_dump() == \
        service.analytics_from_items(full, service.kpis(full, []), filters).model_dump()


def test_overview_reused_own_facts_preserve_active_account_role_and_platform_scope(context, service):
    from tests.competitors.test_api import account, instagram
    from app.services.overview_service import OverviewService
    instagram(context)
    inactive = account(context, role='OWN', active=False)
    add_post(context, metrics={'reach':100, 'likes':1})
    for fields in [{'account_id': inactive}, {'account_id': None}, {'platform':'INSTAGRAM'},
                   {'account_id': context.competitor_id}]:
        add_post(context, metrics={'reach':100, 'likes':999}, **fields)
    add_post(context, account_id=context.competitor_id, source_type='COMPETITOR', metrics={'reach':100,'likes':2})
    filters = service.filters(START, END)
    overview = OverviewService(context.factory)
    with overview.read(context.project_id) as s:
        accounts = overview.repository.accounts(s, context.project_id, ['X', 'INSTAGRAM'])
        rows = overview.competitor.repository.period_posts(s, context.project_id, accounts, filters)
        followers = overview.competitor.repository.account_followers(s, accounts, END)
        own_accounts = [a for a in accounts if a['role'] == 'OWN']
        own_ids = {a['account_id'] for a in own_accounts}
        old_items = [overview.own.item(r) for r in rows if r['account_id'] in own_ids]
        expected = overview.summary(old_items, own_accounts, followers)
    result = overview.overview(context.project_id, filters)
    assert result.own_summary.model_dump() == expected.model_dump()
    assert result.own_summary.posts == 1
    assert result.kpis.posts.value == 5
    assert result.competitor_aggregate.posts == 1
