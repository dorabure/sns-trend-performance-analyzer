import json
from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import select,func,event
from sqlalchemy.orm import sessionmaker
from app.db.models import Project,ImportHistory,SNSAccount,SNSPost,PostMetric,PostTopic,PostTerm,TrendDaily,AIInsight,WatchTopic
from app.demo.generator import ANCHOR,TOPICS,SEED,generate
from app.demo.loader import PROJECT_ID,MARKER,stable,load,setup
from app.demo.fixture_ai import DemoClient
from app.services.my_account_service import MyAccountService,Filters
from app.services.insight_service import InsightService,snapshot_input,without_names
from app.services.overview_service import OverviewService
from app.services.settings_service import SettingsFailure

FIRST=ANCHOR-timedelta(days=89)
BASE=f"/api/v1/projects/{PROJECT_ID}"
def get(client,path,params):
    response=client.get(BASE+path,params=params)
    assert response.status_code==200,response.text
    return response.json()

def test_import_counts_matching_sources_and_no_processing(demo):
    factory,_,result=demo
    assert [r['status'] for r in result['imports']]==['SUCCESS']*4
    assert [r['rows'] for r in result['imports']]==[180,540,180,4500]
    with factory() as s:
        assert dict(s.execute(select(SNSPost.source_type,func.count()).group_by(SNSPost.source_type)).all())=={'OWN':180,'COMPETITOR':540,'MARKET':4500}
        histories=s.scalars(select(ImportHistory)).all()
        assert len(histories)==4 and all(h.status=='SUCCESS' and h.error_count==0 for h in histories)
        assert s.scalar(select(func.count()).select_from(PostMetric))==5220
        assert s.scalar(select(func.count()).select_from(PostTopic))>5220
        assert s.scalar(select(func.count()).select_from(PostTerm))>5220
        assert s.scalar(select(func.count()).select_from(TrendDaily))>2000
        assert s.scalar(select(func.count()).select_from(WatchTopic))==6
        assert s.scalar(select(func.count()).select_from(SNSAccount).where(SNSAccount.account_role=='COMPETITOR'))==3

def test_safe_repeat_no_growth(demo):
    factory,_,_=demo
    with factory() as s:
        before=[s.scalar(select(func.count()).select_from(model)) for model in (SNSPost,PostMetric,ImportHistory,AIInsight)]
    with pytest.raises(ValueError,match='already exists'): load(factory)
    with factory() as s: assert before==[s.scalar(select(func.count()).select_from(model)) for model in (SNSPost,PostMetric,ImportHistory,AIInsight)]

def test_reserved_reset_preserves_user_and_refuses_marker_mismatch(postgres_engine):
    factory=sessionmaker(postgres_engine,expire_on_commit=False)
    user=uuid4()
    from sqlalchemy import delete
    try:
        with factory() as s,s.begin(): s.add(Project(project_id=user,name='Unrelated user project'))
        setup(factory)
        with factory() as s,s.begin(): s.get(Project,PROJECT_ID).description='User changed marker'
        with pytest.raises(ValueError,match='marker mismatch'): setup(factory,True)
        with factory() as s,s.begin():
            assert s.get(Project,user).name=='Unrelated user project'
            s.get(Project,PROJECT_ID).description=MARKER
        setup(factory,True)
        with factory() as s:
            assert s.get(Project,user).name=='Unrelated user project'
            assert s.get(Project,PROJECT_ID).description==MARKER
            assert s.scalar(select(func.count()).select_from(SNSAccount).where(SNSAccount.project_id==PROJECT_ID))==5
    finally:
        with factory() as s,s.begin(): s.execute(delete(Project).where(Project.project_id.in_([user,PROJECT_ID])))

@pytest.mark.parametrize('platform',['ALL','X','INSTAGRAM'])
@pytest.mark.parametrize('days',[7,30,90,17])
def test_matrix_cross_screen_and_real_evidence(client,demo,platform,days):
    params={'platform':platform,'from':(ANCHOR-timedelta(days=days-1)).isoformat(),'to':ANCHOR.isoformat()}
    overview=get(client,'/dashboard/overview',params)
    own=get(client,'/accounts/own/analytics',params)['kpis']
    assert own['posts']==days*(2 if platform=='ALL' else 1)
    for key in ('posts','reach','impressions','engagement','engagement_rate','followers'):
        assert own[key]==overview['kpis'][key]['value']
    assert own['rate_groups']==overview['kpis']['engagement_rate']['rate_groups']
    if platform=='ALL': assert own['followers'] is None and own['engagement_rate'] is None
    gap=get(client,'/gap-analysis',params)['items']
    assert overview['top_opportunity']==next(i for i in gap if i['gap_score'] is not None)
    for trend in overview['top_trends']:
        match=next(i for i in gap if i['topic_id']==trend['topic_id'] and i['platform']==trend['platform'])
        assert trend['trend_score']==match['trend_score'] and trend['trend_date']==match['trend_date']
    factory,_,_=demo
    filters=MyAccountService.filters(ANCHOR-timedelta(days=days-1),ANCHOR,platform)
    summary,evidence=snapshot_input(PROJECT_ID,filters,OverviewService(factory).overview(PROJECT_ID,filters))
    assert summary['market_trends']==overview['top_trends'] and summary['opportunity']==overview['top_opportunity']
    assert next(i.values for i in evidence.kpis if i.id=='KPI_REACH')==overview['kpis']['reach']
    with factory() as s:
        accounts=s.scalars(select(SNSAccount).where(SNSAccount.account_role=='COMPETITOR')).all()
    ids=[a.account_id for a in accounts if platform=='ALL' or a.platform==platform]
    comp=get(client,'/competitors/analytics',dict(params,account_ids=','.join(map(str,ids))))['accounts']
    mapped={a['account_id']:a for a in comp if a['role']=='COMPETITOR'}
    for a in overview['competitor_summary']: assert a==mapped[a['account_id']]
    # Preserve original ordering contracts while associating values by IDs.
    assert [(a['role'],a['platform'],a['account_name']) for a in comp]==[(a['role'],a['platform'],a['account_name']) for a in sorted(comp,key=lambda a:(0 if a['role']=='OWN' else 1,a['platform'],a['account_name'],a['account_id']))]
    assert [a['account_name'] for a in overview['competitor_summary']]==sorted(a['account_name'] for a in overview['competitor_summary'])
    topic=stable('topic:'+TOPICS[0][0])
    rank=get(client,'/trends/ranking',dict(params,topic_id=str(topic)))['items']
    assert rank
    for item in rank:
        assert item['platform'] in ({'X','INSTAGRAM'} if platform=='ALL' else {platform})
    popular=get(client,f'/trends/{topic}/top-posts',params)['items']
    assert popular and all(p['account_id'] is None for p in popular)

def test_four_gap_classes_and_null_zero_media(client,demo):
    params={'platform':'ALL','from':FIRST.isoformat(),'to':ANCHOR.isoformat()}
    gap=get(client,'/gap-analysis',params)['items']
    assert {i['classification'] for i in gap if i['classification'] is not None}=={'OPPORTUNITY','BALANCED','HIGH_COVERAGE','LOW_PRIORITY'}
    assert any(i['gap_score']==0 for i in gap)
    assert any(i['trend_score'] is None and i['gap_score'] is None and i['classification'] is None for i in gap)
    factory,_,_=demo
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(PostMetric).join(SNSPost).where(SNSPost.source_type=='OWN',PostMetric.reach.is_(None)))==2
        assert s.scalar(select(func.count()).select_from(PostMetric).join(SNSPost).where(SNSPost.source_type=='OWN',PostMetric.reach==0))==2
        assert set(s.scalars(select(SNSPost.media_type).where(SNSPost.source_type=='OWN')))=={'TEXT','IMAGE','VIDEO','CAROUSEL'}
    zero=get(client,'/accounts/own/analytics',dict(params,**{'from':(FIRST+timedelta(days=86)).isoformat(),'to':(FIRST+timedelta(days=86)).isoformat()}))['kpis']
    null=get(client,'/accounts/own/analytics',dict(params,**{'from':(FIRST+timedelta(days=87)).isoformat(),'to':(FIRST+timedelta(days=87)).isoformat()}))['kpis']
    assert zero['reach']==0 and zero['engagement']==0 and zero['engagement_rate'] is None
    assert null['reach'] is None and null['engagement'] is None

@pytest.mark.parametrize('before',[True,False])
def test_outside_period_empty_keeps_null_not_zero(client,before):
    day=FIRST-timedelta(days=1) if before else ANCHOR+timedelta(days=1)
    params={'platform':'ALL','from':day.isoformat(),'to':day.isoformat()}
    own=get(client,'/accounts/own/analytics',params)['kpis']
    assert own['posts']==0 and own['reach'] is None
    gap=get(client,'/gap-analysis',params)['items']
    assert len(gap)==12 and all(i['own_post_ratio'] is None and i['gap_score'] is None for i in gap)

def test_saved_demo_ai_available_without_key_and_matches_snapshot(client,demo):
    params={'platform':'ALL','from':FIRST.isoformat(),'to':ANCHOR.isoformat()}
    latest=get(client,'/insights/latest',params)
    assert latest['ai_generation_available'] is False
    insight=latest['insight'];assert insight['model_name']=='demo-fixture' and '実OpenAI生成ではありません' in insight['content']['summary']
    overview=get(client,'/dashboard/overview',params)
    assert insight['input_summary']['own_kpi']==without_names(overview['kpis'])
    ids={i['id'] for group in insight['evidence'].values() for i in group}
    refs=insight['content']['references']
    assert set(refs['market_trend']+refs['own_analysis']+sum(refs['improvement_points']+refs['post_ideas'],[]))<=ids
    count=demo[2]['fixture_calls']; assert count==1 and demo[2]['live_openai_calls']==0
    response=client.post(BASE+'/insights/generate',json=params)
    assert response.status_code==503 and response.json()['error']['code']=='AI_KEY_NOT_CONFIGURED'

def test_distinct_trend_scenarios_are_calculated(demo):
    factory,_,_=demo
    with factory() as s:
        rows=s.scalars(select(TrendDaily).where(TrendDaily.term_id.is_(None))).all()
        assert any(r.post_growth_rate is not None and r.post_growth_rate>0 for r in rows)
        assert any(r.post_growth_rate is not None and r.post_growth_rate<0 for r in rows)
        latest={r.topic_id:r.trend_score for r in rows if r.trend_date==ANCHOR and r.platform=='X'}
        assert latest[stable('topic:'+TOPICS[0][0])]>latest[stable('topic:'+TOPICS[2][0])]
        assert len(set(latest.values()))>=4


def test_canonical_query_counts_and_payload_bounds(demo):
    from app.demo.audit import audit
    result=audit(demo[0],demo[1],ANCHOR)
    assert {key:value['select_count'] for key,value in result['queries'].items()}==dict(own_list=3,trend_ranking=5,popular_posts=5,competitor_top=4,gap=6,overview=16)
    assert result['ai_payload_bytes']<40000
    assert result['gap_zero']==2 and result['gap_null']==1
