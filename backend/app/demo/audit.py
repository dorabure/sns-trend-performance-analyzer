"""Read-only demo measurements, not a production endpoint."""
import json
from datetime import timedelta
from time import perf_counter
from sqlalchemy import event,func,select
from app.db.models import SNSAccount,SNSPost,PostMetric,PostTopic,PostTerm,TrendDaily,AccountMetric,ImportHistory,AIInsight,WatchTopic,WatchTerm
from app.demo.generator import ANCHOR,TOPICS
from app.demo.loader import PROJECT_ID,stable
from app.services.my_account_service import MyAccountService,Filters
from app.services.trend_explorer_service import TrendExplorerService
from app.services.competitor_service import CompetitorService
from app.services.gap_analysis_service import GapAnalysisService
from app.services.overview_service import OverviewService
from app.services.insight_service import snapshot_input

def audit(factory,engine,anchor=ANCHOR):
    filters=Filters(start=anchor-timedelta(days=89),end=anchor)
    with factory() as s:
        ids=list(s.scalars(select(SNSAccount.account_id).where(SNSAccount.project_id==PROJECT_ID,SNSAccount.account_role=='COMPETITOR')))
        post_ids=select(SNSPost.post_id).where(SNSPost.project_id==PROJECT_ID)
        account_ids=select(SNSAccount.account_id).where(SNSAccount.project_id==PROJECT_ID)
        topic_ids=select(WatchTopic.topic_id).where(WatchTopic.project_id==PROJECT_ID)
        counts={model.__tablename__:s.scalar(select(func.count()).select_from(model).where(condition)) for model,condition in [
            (SNSPost,SNSPost.project_id==PROJECT_ID),(PostMetric,PostMetric.post_id.in_(post_ids)),
            (PostTopic,PostTopic.post_id.in_(post_ids)),(PostTerm,PostTerm.post_id.in_(post_ids)),
            (TrendDaily,TrendDaily.topic_id.in_(topic_ids)),(AccountMetric,AccountMetric.account_id.in_(account_ids)),
            (ImportHistory,ImportHistory.project_id==PROJECT_ID),(AIInsight,AIInsight.project_id==PROJECT_ID),
            (WatchTopic,WatchTopic.project_id==PROJECT_ID),(WatchTerm,WatchTerm.topic_id.in_(topic_ids)),
            (SNSAccount,SNSAccount.project_id==PROJECT_ID)]}
    own=MyAccountService(factory); trends=TrendExplorerService(factory); comp=CompetitorService(factory)
    gap=GapAnalysisService(factory);overview=OverviewService(factory)
    topic=stable('topic:'+TOPICS[0][0])
    operations={'own_list':lambda:own.posts(PROJECT_ID,filters,1,20,'posted_at','desc'),
        'trend_ranking':lambda:trends.ranking(PROJECT_ID,topic,filters,20),
        'popular_posts':lambda:trends.top_posts(PROJECT_ID,topic,filters,10),
        'competitor_top':lambda:comp.top_posts(PROJECT_ID,ids,filters,10),
        'gap':lambda:gap.analysis(PROJECT_ID,filters),'overview':lambda:overview.overview(PROJECT_ID,filters)}
    measurements={};results={}
    for name,operation in operations.items():
        count=0
        def query(conn,cursor,statement,params,context,many):
            nonlocal count
            if statement.lstrip().split()[0] in ('SELECT','WITH'):count+=1
        event.listen(engine,'before_cursor_execute',query)
        start=perf_counter()
        try: results[name]=operation()
        finally: event.remove(engine,'before_cursor_execute',query)
        measurements[name]=dict(select_count=count,seconds=perf_counter()-start)
    summary,evidence=snapshot_input(PROJECT_ID,filters,results['overview'])
    external=dict(summary,analysis_scope={k:v for k,v in summary['analysis_scope'].items() if k!='project_id'})
    classes=sorted({i.classification.value for i in results['gap'].items if i.classification})
    return dict(db_counts=counts,queries=measurements,gap_classes=classes,
        gap_zero=sum(i.gap_score==0 for i in results['gap'].items),gap_null=sum(i.gap_score is None for i in results['gap'].items),
        top_trends=[dict(topic=t.topic_name,platform=t.platform,score=t.trend_score) for t in results['overview'].top_trends],
        ai_payload_bytes=len(json.dumps([external,evidence.model_dump(mode='json')],ensure_ascii=False).encode('utf-8')))
