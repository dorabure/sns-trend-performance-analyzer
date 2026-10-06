from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event, select, text

from app.db.models import PostTerm, PostTopic, Project, ProjectPlatform, TrendDaily, WatchTerm, WatchTopic
from app.services.trend_explorer_service import direction
from tests.my_account.test_api import add_post

DAY = date(2026, 10, 3)
QUERY = "from=2026-10-01&to=2026-10-03"


def path(c): return f"/api/v1/projects/{c.project_id}/trends"
def ranking(client, c, extra="", query=QUERY):
    return client.get(path(c)+f"/ranking?topic_id={c.topic_id}&{query}"+extra)
def series(client, c, ids=None, extra="", query=QUERY):
    ids = ids or [c.terms["ChatGPT"]]
    return client.get(path(c)+f"/timeseries?term_ids={','.join(map(str, ids))}&{query}"+extra)
def popular(client, c, extra="", query=QUERY):
    return client.get(path(c)+f"/{c.topic_id}/top-posts?{query}"+extra)


def snapshot(c, term="ChatGPT", day=DAY, platform="X", **fields):
    with c.factory() as s, s.begin():
        row = TrendDaily(topic_id=c.topic_id, term_id=c.terms[term] if term else None,
                         platform=platform, trend_date=day, post_count=2, engagement_count=9)
        for key, value in fields.items(): setattr(row,key,value)
        s.add(row)


def market(c, term="ChatGPT", topic=True, **fields):
    source = fields.pop("source_type", "MARKET")
    post = add_post(c, source_type=source, account_id=None if source=="MARKET" else c.own_id, **fields)
    with c.factory() as s, s.begin():
        if topic: s.add(PostTopic(post_id=post, topic_id=c.topic_id, match_type="KEYWORD"))
        if term: s.add(PostTerm(post_id=post, term_id=c.terms[term], match_method="EXACT"))
    return post


def test_empty(client, context):
    assert ranking(client,context).json()=={"score_window_days":7,"score_as_of":None,"items":[]}
    assert popular(client,context).json()=={"items":[]}
    result=series(client,context).json()
    assert result["metric"]=="post_count" and result["timezone"]=="UTC"
    assert len(result["series"])==1
    assert all(v["value"] is None and not v["row_present"] for v in result["series"][0]["values"])


def test_latest_term_snapshot_not_topic_or_sum(client,context):
    snapshot(context, day=date(2026,10,1),post_count=999,trend_score=99)
    snapshot(context, day=date(2026,10,2),post_count=4,trend_score=12)
    snapshot(context, day=date(2026,10,4),post_count=100,trend_score=100)
    snapshot(context, term=None,trend_score=100)
    result=ranking(client,context).json()
    assert len(result["items"])==1
    row=result["items"][0]
    assert row["post_count"]==4 and row["trend_score"]==12 and row["trend_date"]=="2026-10-02"
    assert result["score_as_of"]=="2026-10-02"
    assert ranking(client,context,query="from=2026-10-03&to=2026-10-03").json()["items"]==[]


@pytest.mark.parametrize("value,expected",[(None,"UNKNOWN"),(0,"FLAT"),(Decimal("0.0001"),"UP"),(-30,"DOWN")])
def test_direction_saved_value(client,context,value,expected):
    snapshot(context,post_growth_rate=value)
    row=ranking(client,context).json()["items"][0]
    assert row["trend_direction"]==expected and direction(value)==expected
    assert row["post_growth_rate"]==(float(value) if value is not None else None)


def test_ranking_null_sort_and_limit_stable(client,context):
    for term,score in [("ChatGPT",0),("AI",20),("生成AI",20),("#ChatGPT",None)]:
        snapshot(context,term=term,trend_score=score)
    rows=ranking(client,context).json()["items"]
    assert [r["keyword"] for r in rows]==["AI","生成AI","ChatGPT","#ChatGPT"]
    assert ranking(client,context,"&limit=2").json()["items"]==rows[:2]
    assert rows[-1]["trend_score"] is None
    for key in ("post_growth_rate","engagement_growth_rate","avg_engagement","acceleration_rate"):
        assert rows[-1][key] is None


@pytest.mark.parametrize("keyword,count",[("ＣＨＡＴｇｐｔ",2),("  chatGPT ",2),("%",0),("_",0),(" ",3),("x' OR 1=1--",0)])
def test_unicode_literal_keyword(client,context,keyword,count):
    for term in ("ChatGPT","#ChatGPT","AI"): snapshot(context,term=term)
    result=client.get(path(context)+"/ranking",params={"topic_id":str(context.topic_id),"from":"2026-10-01","to":"2026-10-03","keyword":keyword})
    assert result.status_code==200 and len(result.json()["items"])==count


@pytest.mark.parametrize("platform,count",[("ALL",2),("X",1),("INSTAGRAM",1)])
def test_platform_separation(client,context,platform,count):
    with context.factory() as s,s.begin(): s.add(ProjectPlatform(project_id=context.project_id,platform="INSTAGRAM"))
    snapshot(context,platform="X",post_count=3)
    snapshot(context,platform="INSTAGRAM",post_count=8)
    rows=ranking(client,context,"&platform="+platform).json()["items"]
    assert len(rows)==count and all(r["post_count"] in (3,8) for r in rows)
    assert len(series(client,context,extra="&platform="+platform).json()["series"])==count


def test_disabled_platform(client,context):
    snapshot(context,platform="INSTAGRAM",trend_score=90)
    assert ranking(client,context).json()["items"]==[]
    assert series(client,context,extra="&platform=INSTAGRAM").json()["series"]==[]
    market(context,platform="INSTAGRAM",metrics={"likes":99})
    assert popular(client,context).json()["items"]==[]


@pytest.mark.parametrize("metric,expected",[("post_count",0),("engagement",0),("trend_score",None)])
def test_timeseries_zero_null_missing_and_boundaries(client,context,metric,expected):
    snapshot(context,day=date(2026,9,30),post_count=99)
    snapshot(context,day=date(2026,10,1),post_count=0,engagement_count=0)
    snapshot(context,day=date(2026,10,3),post_count=7,engagement_count=8,trend_score=0)
    snapshot(context,day=date(2026,10,4),post_count=99)
    result=series(client,context,extra="&metric="+metric).json()["series"][0]
    assert result["term_name"]==result["term"]=="ChatGPT"
    assert result["values"][0]=={"date":"2026-10-01","value":expected,"row_present":True}
    assert result["values"][1]=={"date":"2026-10-02","value":None,"row_present":False}
    assert result["values"][2]["row_present"] and result["values"][2]["value"]=={"post_count":7,"engagement":8,"trend_score":0}[metric]


def test_multi_term_and_keyword_scope(client,context):
    snapshot(context,term="ChatGPT",post_count=13)
    snapshot(context,term="AI",post_count=17)
    ids=[context.terms["ChatGPT"],context.terms["AI"]]
    rows=series(client,context,ids).json()["series"]
    assert len(rows)==2 and {r["values"][-1]["value"] for r in rows}=={13,17}
    assert len(series(client,context,ids,extra="&keyword=CHATGPT").json()["series"])==1


@pytest.mark.parametrize("kind",["topic","term"])
def test_inactive_scope(client,context,kind):
    snapshot(context)
    with context.factory() as s,s.begin():
        entity=s.get(WatchTopic,context.topic_id) if kind=="topic" else s.get(WatchTerm,context.terms["ChatGPT"])
        entity.is_active=False
    if kind=="topic":
        assert ranking(client,context).status_code==popular(client,context).status_code==404
    else: assert ranking(client,context).json()["items"]==[]
    assert series(client,context).status_code==404


def test_popular_market_topic_term_latest_and_sort(client,context):
    first=market(context,snapshots=[{"likes":999},{"likes":3,"comments":2,"saves":1}])
    zero=market(context,metrics={"likes":0})
    unknown=market(context,metrics={})
    other=market(context,term="AI",metrics={"likes":20})
    market(context,source_type="OWN",metrics={"likes":1000})
    market(context,source_type="COMPETITOR",metrics={"likes":1000})
    market(context,topic=False,metrics={"likes":1000})
    rows=popular(client,context).json()["items"]
    assert [p["post_id"] for p in rows]==list(map(str,[other,first,zero,unknown]))
    assert [p["engagement"] for p in rows]==[20,6,0,None]
    assert popular(client,context,"&limit=1").json()["items"][0]["post_id"]==str(other)
    assert len(popular(client,context,"&term_id="+str(context.terms["ChatGPT"])).json()["items"])==3
    assert len(popular(client,context,"&keyword=ＡＩ").json()["items"])==1


@pytest.mark.parametrize("stamp,included",[("2026-09-30T23:59:59.999999+00:00",False),("2026-10-01T00:00:00+00:00",True),("2026-10-03T23:59:59.999999+00:00",True),("2026-10-04T00:00:00+00:00",False),("2026-10-01T08:59:59+09:00",False)])
def test_popular_utc(client,context,stamp,included):
    market(context,posted_at=datetime.fromisoformat(stamp),metrics={"likes":1})
    assert len(popular(client,context).json()["items"])==int(included)


def test_popular_null_snapshot_tie_and_platform(client,context):
    a=market(context,snapshots=[{"likes":500},{}])
    b=market(context,metrics={"likes":0})
    c=market(context,metrics={"likes":0})
    rows=popular(client,context).json()["items"]
    assert [r["post_id"] for r in rows]==sorted([str(b),str(c)])+[str(a)]
    assert rows[-1]["likes"] is None
    assert popular(client,context,"&platform=INSTAGRAM").json()["items"]==[]


def test_cross_project_topic_term_and_corrupt_trend(client,context):
    with context.factory() as s,s.begin():
        p=Project(name="Other scope");s.add(p);s.flush()
        topic=WatchTopic(project_id=p.project_id,topic_name="Other");s.add(topic);s.flush()
        term=WatchTerm(topic_id=topic.topic_id,term="foreign",normalized_term="foreign",term_type="KEYWORD");s.add(term);s.flush()
        # Individual foreign keys allow inconsistent topic/term; reader must verify their relationship.
        s.add(TrendDaily(topic_id=context.topic_id,term_id=term.term_id,platform="X",trend_date=DAY,trend_score=100))
        s.add(TrendDaily(topic_id=topic.topic_id,term_id=context.terms["ChatGPT"],platform="X",trend_date=DAY,trend_score=100))
        tid,termid=topic.topic_id,term.term_id
    try:
        assert ranking(client,context).json()["items"]==[]
        assert series(client,context,[termid]).status_code==404
        assert client.get(path(context)+f"/ranking?topic_id={tid}&{QUERY}").status_code==404
        assert client.get(path(context)+f"/{tid}/top-posts?{QUERY}").status_code==404
        assert popular(client,context,"&term_id="+str(termid)).status_code==404
        assert all(v["value"] is None for v in series(client,context).json()["series"][0]["values"])
        # A MARKET post from the foreign project linked to this topic must still be excluded.
        market(context,project_id=p.project_id,metrics={"likes":1000})
        assert popular(client,context).json()["items"]==[]
    finally:
        with context.factory() as s, s.begin():
            s.execute(delete(Project).where(Project.project_id == p.project_id))


@pytest.mark.parametrize("endpoint,extra,status",[("ranking","&limit=0",422),("ranking","&limit=101",422),("popular","&limit=0",422),("popular","&limit=51",422),("ranking","&platform=BAD",422),("series","&metric=BAD",422),("ranking","&keyword="+"x"*1001,422),("popular","&term_id=bad",422)])
def test_typed_validation(client,context,endpoint,extra,status):
    r={"ranking":ranking,"series":series,"popular":popular}[endpoint](client,context,extra=extra)
    assert r.status_code==status and "error" in r.json() and "input" not in r.text


@pytest.mark.parametrize("query,status",[("from=2026-10-04&to=2026-10-03",400),("from=2000-01-01&to=2026-10-03",400),("from=bad&to=2026-10-03",422),("from=2026-10-01",422)])
def test_period_validation(client,context,query,status):
    for call in (ranking,series,popular): assert call(client,context,query=query).status_code==status


@pytest.mark.parametrize("ids",["","bad","a' OR 1=1--",','.join([str(uuid4())]*6),','.join([str(UUID(int=1))]*2)])
def test_selected_term_validation(client,context,ids):
    r=client.get(path(context)+f"/timeseries?{QUERY}",params={"term_ids":ids})
    assert r.status_code==422 and "error" in r.json() and "input" not in r.text


@pytest.mark.parametrize("endpoint",["ranking","timeseries","popular"])
def test_missing_project(client,context,endpoint):
    prefix=f"/api/v1/projects/{uuid4()}/trends"
    suffix=f"/ranking?topic_id={context.topic_id}" if endpoint=="ranking" else f"/timeseries?term_ids={context.terms['ChatGPT']}" if endpoint=="timeseries" else f"/{context.topic_id}/top-posts?"
    assert client.get(prefix+suffix+"&"+QUERY).status_code==404


def test_fault_secret_scrub(client,context,service,monkeypatch):
    def fail(*args,**kwargs): raise RuntimeError("password=secret SELECT * FROM private")
    monkeypatch.setattr(service.repository,"snapshots",fail)
    r=ranking(client,context)
    assert r.status_code==500 and "secret" not in r.text and "SELECT" not in r.text


def test_1000_snapshots_posts_fixed_queries_readonly(client,context,service):
    ids=list(context.terms.values())
    with context.factory() as s,s.begin():
        s.add_all([TrendDaily(topic_id=context.topic_id,term_id=term,platform="X",
            trend_date=DAY-timedelta(days=day),post_count=day,engagement_count=day,trend_score=50)
            for term in ids for day in range(200)])
    # Bulk insert test posts/links/snapshots, without per-post reads.
    from app.db.models import SNSPost, PostMetric
    with context.factory() as s,s.begin():
        postids=[uuid4() for _ in range(1000)]
        s.add_all([SNSPost(post_id=id,project_id=context.project_id,source_type="MARKET",platform="X",
            platform_post_id=str(id),posted_at=datetime(2026,10,3,tzinfo=timezone.utc),hashtags=[],raw_data={}) for id in postids]);s.flush()
        s.add_all([PostTopic(post_id=id,topic_id=context.topic_id,match_type="KEYWORD") for id in postids])
        s.add_all([PostMetric(post_id=id,recorded_at=datetime(2026,10,3,tzinfo=timezone.utc),likes=1,raw_metrics={}) for id in postids])
    engine=context.factory.kw["bind"]; statements=[]
    def capture(conn,cursor,statement,parameters,ctx,many): statements.append(statement)
    event.listen(engine,"before_cursor_execute",capture)
    try:
        for call,bound in [(lambda:ranking(client,context),5),(lambda:series(client,context,ids),4),(lambda:popular(client,context),5)]:
            statements.clear();r=call();assert r.status_code==200,r.text
            assert sum(q.lstrip().upper().startswith(("SELECT", "WITH")) for q in statements)<=bound
            assert not any(q.lstrip().upper().startswith(("INSERT","UPDATE","DELETE","COMMIT")) for q in statements)
        with service.read(context.project_id) as s:
            assert s.scalar(text("SHOW transaction_read_only"))=="on"
            assert s.scalar(text("SHOW transaction_isolation"))=="repeatable read"
    finally: event.remove(engine,"before_cursor_execute",capture)
