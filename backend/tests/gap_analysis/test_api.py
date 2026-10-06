from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, insert, select, text

from app.db.models import PostTerm, PostTopic, Project, SNSAccount, SNSPost, TrendDaily, WatchTopic
from app.repositories.gap_analysis_repository import GapAnalysisRepository
from app.services.gap_analysis_service import GapAnalysisService
from tests.competitors.test_api import account, instagram, match
from tests.imports.conftest import T1
from tests.my_account.test_api import add_post

PERIOD = 'from=2026-10-01&to=2026-10-03'


def url(c, query=PERIOD): return f'/api/v1/projects/{c.project_id}/gap-analysis?{query}'


def get(client,c,query=PERIOD):
    r=client.get(url(c,query)); assert r.status_code==200,r.text
    return r.json()


def snapshot(c, score=80, day=date(2026,10,3), platform='X', topic_id=None, term_id=None):
    with c.factory() as s, s.begin():
        s.add(TrendDaily(topic_id=topic_id or c.topic_id, term_id=term_id, platform=platform,
                         trend_date=day, trend_score=score, post_count=100))


def test_empty_active_topic_retained(client,context):
    result=get(client,context)
    assert (result['timezone'],result['from'],result['to'],result['score_window_days'])==('UTC','2026-10-01','2026-10-03',7)
    assert result['trend_threshold']==result['own_ratio_threshold']==50
    assert len(result['items'])==1
    p=result['items'][0]
    assert p['topic_name']=='AI' and p['platform']=='X'
    assert all(p[k] is None for k in ('trend_date','trend_score','own_post_ratio','competitor_post_ratio','gap_score','classification'))
    assert all(p[k]==0 for k in ('own_posts','own_total_posts','competitor_posts','competitor_total_posts'))


def test_no_active_topics_empty(client,context):
    with context.factory() as s,s.begin(): s.get(WatchTopic,context.topic_id).is_active=False
    assert get(client,context)['items']==[]


@pytest.mark.parametrize('score',[None,0,80])
def test_latest_topic_snapshot_not_sum_average_or_null_backfill(client,context,score):
    for day,value in [(date(2026,9,30),90),(date(2026,10,1),10),(date(2026,10,3),score),(date(2026,10,4),99)]:
        snapshot(context,value,day)
    snapshot(context,99,term_id=context.terms['ChatGPT'])
    add_post(context)
    p=get(client,context)['items'][0]
    assert p['trend_date']=='2026-10-03' and p['trend_score']==score
    assert p['own_post_ratio']==0 and p['gap_score']==score
    earlier=get(client,context,'from=2026-10-01&to=2026-10-02')['items'][0]
    assert earlier['trend_score']==10 and earlier['trend_date']=='2026-10-01'


def test_term_only_and_before_period_not_used(client,context):
    snapshot(context,99,term_id=context.terms['ChatGPT'])
    snapshot(context,88,date(2026,9,30))
    p=get(client,context)['items'][0]
    assert p['trend_date'] is None and p['trend_score'] is None


@pytest.mark.parametrize('method',['KEYWORD','HASHTAG','MANUAL','AI'])
def test_own_ratio_existing_matches_only_no_rematch_or_terms(client,context,method):
    snapshot(context)
    posts=[add_post(context,text='ChatGPT') for _ in range(4)]
    match(context,posts[0],kind=method)
    with context.factory() as s,s.begin(): s.add(PostTerm(post_id=posts[1],term_id=context.terms['ChatGPT'],match_method='MANUAL'))
    p=get(client,context)['items'][0]
    assert (p['own_posts'],p['own_total_posts'],p['own_post_ratio'],p['gap_score'],p['classification'])==(1,4,25,60,'OPPORTUNITY')


def test_competitor_all_active_post_weighted_not_average(client,context):
    other=account(context); inactive=account(context,active=False)
    for acc,count,matched_count in [(context.competitor_id,1,1),(other,9,0),(inactive,10,10)]:
        for i in range(count):
            post=add_post(context,account_id=acc,source_type='COMPETITOR')
            if i<matched_count: match(context,post)
    own=add_post(context); match(context,own)
    match(context,add_post(context,source_type='MARKET',account_id=None))
    snapshot(context)
    p=get(client,context)['items'][0]
    assert (p['competitor_posts'],p['competitor_total_posts'],p['competitor_post_ratio'])==(1,10,10)
    assert p['own_total_posts']==1 and p['gap_score']==0 and p['classification']=='BALANCED'


def test_inactive_own_history_kept_consistent_with_phase7(client,context):
    match(context,add_post(context))
    with context.factory() as s,s.begin(): s.get(SNSAccount,context.own_id).is_active=False
    p=get(client,context)['items'][0]
    assert p['own_total_posts']==1 and p['own_post_ratio']==100


def test_all_platforms_separate_ratio_and_snapshot(client,context):
    own_ig,comp_ig=instagram(context)
    snapshot(context,80);snapshot(context,20,platform='INSTAGRAM')
    add_post(context);match(context,add_post(context,account_id=own_ig,platform='INSTAGRAM'))
    add_post(context,account_id=context.competitor_id,source_type='COMPETITOR')
    match(context,add_post(context,account_id=comp_ig,platform='INSTAGRAM',source_type='COMPETITOR'))
    items=get(client,context)['items'];assert len(items)==2
    x=next(p for p in items if p['platform']=='X');ig=next(p for p in items if p['platform']=='INSTAGRAM')
    assert (x['own_post_ratio'],x['competitor_post_ratio'],x['gap_score'],x['classification'])==(0,0,80,'OPPORTUNITY')
    assert (ig['own_post_ratio'],ig['competitor_post_ratio'],ig['gap_score'],ig['classification'])==(100,100,0,'HIGH_COVERAGE')
    for platform in ('X','INSTAGRAM'):
        assert [p['platform'] for p in get(client,context,PERIOD+f'&platform={platform}')['items']]==[platform]


def test_utc_boundaries_and_missing_post_metrics(client,context):
    start=T1.replace(day=1,hour=0);end=T1.replace(day=3,hour=23,minute=59,second=59,microsecond=999999)
    for source,acc in [('OWN',context.own_id),('COMPETITOR',context.competitor_id)]:
        for instant in (start-timedelta(microseconds=1),start,end,end+timedelta(microseconds=1)):
            match(context,add_post(context,account_id=acc,source_type=source,posted_at=instant))
    p=get(client,context)['items'][0]
    assert p['own_total_posts']==p['own_posts']==p['competitor_total_posts']==p['competitor_posts']==2
    assert p['own_post_ratio']==p['competitor_post_ratio']==100


def test_overlapping_topics_distinct_totals_and_sort(client,context):
    own_ig,_=instagram(context)
    with context.factory() as s,s.begin():
        topics=[WatchTopic(project_id=context.project_id,topic_name=name) for name in ('A','Z','No snapshot')]
        s.add_all(topics);s.flush();ids={t.topic_name:t.topic_id for t in topics}
    x=add_post(context);ig=add_post(context,account_id=own_ig,platform='INSTAGRAM')
    for p in (x,ig):
        match(context,p);match(context,p,ids['A']);match(context,p,ids['Z'])
    for tid in (context.topic_id,ids['A'],ids['Z']):
        for platform in ('X','INSTAGRAM'):snapshot(context,80,topic_id=tid,platform=platform)
    items=get(client,context)['items']
    assert [(p['topic_name'],p['platform']) for p in items]==[(name,platform) for name in ('A','AI','Z','No snapshot') for platform in ('INSTAGRAM','X')]
    assert all(p['own_total_posts']==1 for p in items)
    assert sum(p['own_post_ratio'] for p in items if p['platform']=='X')==300
    assert items[-1]['gap_score'] is None and items[0]['gap_score']==0


def test_cross_project_topic_post_account_and_corrupt_roles(client,context):
    with context.factory() as s,s.begin():
        foreign=Project(name='Gap isolated foreign');s.add(foreign);s.flush()
        topic=WatchTopic(project_id=foreign.project_id,topic_name='Secret topic')
        acc=SNSAccount(project_id=foreign.project_id,platform='X',account_name='foreign',account_role='COMPETITOR')
        s.add_all([topic,acc]);s.flush();foreign_id,topic_id,acc_id=foreign.project_id,topic.topic_id,acc.account_id
    try:
        snapshot(context,99,topic_id=topic_id)
        for fields in [dict(account_id=acc_id,source_type='COMPETITOR'),dict(project_id=foreign_id),
                       dict(source_type='COMPETITOR'),dict(platform='INSTAGRAM'),dict(source_type='MARKET',account_id=None)]:
            match(context,add_post(context,**fields))
        match(context,add_post(context),topic_id)
        own=add_post(context);match(context,own)
        comp=add_post(context,account_id=context.competitor_id,source_type='COMPETITOR');match(context,comp)
        snapshot(context,80)
        p=get(client,context)['items'][0]
        assert p['topic_name']=='AI' and p['trend_score']==80
        assert (p['own_posts'],p['own_total_posts'],p['competitor_posts'],p['competitor_total_posts'])==(1,2,1,1)
    finally:
        with context.factory() as s,s.begin():s.execute(delete(Project).where(Project.project_id==foreign_id))


@pytest.mark.parametrize('query,status',[
    ('from=2026-10-04&to=2026-10-03',400),('from=2000-01-01&to=2026-10-03',400),
    ('from=bad&to=2026-10-03',422),('to=2026-10-03',422),(PERIOD+'&platform=TIKTOK',422),
    (PERIOD+'&platform=INSTAGRAM',404),(PERIOD+'&platform=SELECT secret',422)])
def test_validation(client,context,query,status):
    r=client.get(url(context,query));assert r.status_code==status
    assert 'SELECT secret' not in r.text


def test_unknown_project_and_bad_uuid(client,context):
    assert client.get(url(context).replace(str(context.project_id),str(uuid4()))).status_code==404
    assert client.get(url(context).replace(str(context.project_id),'bad-uuid')).status_code==422


def test_inclusive_3660_day_limit(client,context):
    start=date(2026,10,3)-timedelta(days=3659)
    assert client.get(url(context,f'from={start}&to=2026-10-03')).status_code==200


def test_internal_errors_hidden(client,context,monkeypatch):
    def broken(*args):raise RuntimeError('SELECT data password=secret postgresql://private/path')
    monkeypatch.setattr(GapAnalysisRepository,'snapshots',broken)
    r=client.get(url(context));assert r.status_code==500 and r.json()['error']['code']=='ANALYTICS_ERROR'
    assert all(value not in r.text for value in ('secret','SELECT','postgresql','private/path'))


def test_raw_classification_before_display_rounding(client,context,monkeypatch):
    snapshot(context,50)
    monkeypatch.setattr(GapAnalysisRepository,'coverage',staticmethod(lambda *args:(
        [{'platform':'X','source_type':'OWN','total_posts':100000000}],
        [{'topic_id':context.topic_id,'platform':'X','source_type':'OWN','matched_posts':49999999}])))
    p=get(client,context)['items'][0]
    assert p['own_post_ratio']==50 and p['gap_score']==25 and p['classification']=='OPPORTUNITY'


def test_two_thousand_posts_hundred_topics_two_platforms_fixed_readonly_queries(context):
    own_ig,comp_ig=instagram(context)
    comp_x2=account(context);comp_ig2=account(context,'INSTAGRAM')
    engine=context.factory.kw['bind'];service=GapAnalysisService(context.factory)
    statements,modes=[],[]
    original=service.repository.topics
    def check_topics(s,*args):
        modes.append((s.scalar(text('SHOW transaction_read_only')),s.scalar(text('SHOW transaction_isolation'))))
        return original(s,*args)
    service.repository.topics=check_topics
    def capture(conn,cursor,statement,params,ctx,many):statements.append(statement.strip().split()[0].upper())
    filters=service.filters(date(2026,10,1),date(2026,10,3),'ALL')
    def run():
        statements.clear();event.listen(engine,'before_cursor_execute',capture)
        try:result=service.analysis(context.project_id,filters)
        finally:event.remove(engine,'before_cursor_execute',capture)
        assert not {'INSERT','UPDATE','DELETE','COMMIT'} & set(statements)
        return result,sum(x in ('SELECT','WITH') for x in statements)
    _,small_count=run()
    with context.factory() as s,s.begin():
        topics=[WatchTopic(project_id=context.project_id,topic_name=f'Bulk {i:03}') for i in range(99)]
        s.add_all(topics);s.flush();topic_ids=[context.topic_id]+[t.topic_id for t in topics]
        posts=[];links=[]
        for role in ('OWN','COMPETITOR'):
            for i in range(1000):
                platform='X' if i%2==0 else 'INSTAGRAM'
                acc=(context.own_id if platform=='X' else own_ig) if role=='OWN' else ([context.competitor_id,comp_x2][(i//2)%2] if platform=='X' else [comp_ig,comp_ig2][(i//2)%2])
                pid=uuid4();posts.append(dict(post_id=pid,project_id=context.project_id,account_id=acc,source_type=role,
                    platform=platform,platform_post_id=str(pid),posted_at=T1,text='bulk',raw_data={}))
                links.extend(dict(post_id=pid,topic_id=topic_ids[(i+offset)%100],match_type='AI') for offset in (0,1))
        s.execute(insert(SNSPost),posts);s.execute(insert(PostTopic),links)
        s.execute(insert(TrendDaily),[dict(topic_id=tid,platform=platform,trend_date=date(2026,10,3),trend_score=80)
            for tid in topic_ids for platform in ('X','INSTAGRAM')])
    result,large_count=run()
    assert small_count==large_count==6 and modes==[('on','repeatable read')]*2
    assert len(result.items)==200
    assert all(p.own_total_posts==p.competitor_total_posts==500 for p in result.items)
    assert sum(p.own_posts+p.competitor_posts for p in result.items)==4000
    assert all(p.trend_score==80 and p.gap_score is not None for p in result.items)


@pytest.mark.parametrize('score,matched,total,gap,classification',[
    (80,1,4,60,'OPPORTUNITY'),(100,0,4,100,'OPPORTUNITY'),(100,4,4,0,'BALANCED'),
    (0,2,4,0,'HIGH_COVERAGE'),(20,1,4,15,'LOW_PRIORITY'),(80,0,0,None,None),
    (None,1,4,None,None)])
def test_api_numeric_examples_and_null_propagation(client,context,score,matched,total,gap,classification):
    snapshot(context,score)
    for i in range(total):
        post=add_post(context)
        if i<matched:match(context,post)
    p=get(client,context)['items'][0]
    assert p['gap_score']==gap and p['classification']==classification


def test_gap_descending_then_name_and_null_last(client,context):
    with context.factory() as s,s.begin():
        topics=[WatchTopic(project_id=context.project_id,topic_name=name) for name in ('B high','A high','No trend')]
        s.add_all(topics);s.flush();ids={t.topic_name:t.topic_id for t in topics}
    add_post(context)
    snapshot(context,20)
    snapshot(context,80,topic_id=ids['A high']);snapshot(context,80,topic_id=ids['B high'])
    items=get(client,context)['items']
    assert [(p['topic_name'],p['gap_score']) for p in items]==[('A high',80),('B high',80),('AI',20),('No trend',None)]
