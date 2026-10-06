"""Explicit demo setup through ImportService; reserved project only."""
import argparse
import hashlib
import json
import tempfile
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from time import perf_counter
from uuid import UUID, uuid5
from sqlalchemy import delete, select
from app.db.models import Project, ProjectPlatform, SNSAccount, WatchTopic, WatchTerm
from app.demo.generator import ACCOUNTS, ANCHOR, SEED, TOPICS, FILES, generate
from app.demo.fixture_ai import DemoClient
from app.providers.base import CsvDatasetType
from app.services.import_service import ImportService
from app.services.insight_service import InsightService
from app.services.my_account_service import Filters
from app.services.trend_service import TrendService

PROJECT_ID=UUID("14da0000-1401-5140-8140-000000000014")
MARKER="phase14-v1: fictional canonical demo; reserved project"

def stable(label): return uuid5(PROJECT_ID,label)

class TimedTrend(TrendService):
    def __init__(self): super().__init__(); self.seconds=[]
    def rebuild_project(self, session, project_id):
        start=perf_counter()
        result=super().rebuild_project(session,project_id)
        self.seconds.append(perf_counter()-start)
        return result

def setup(factory, reset=False):
    with factory() as s,s.begin():
        existing=s.scalar(select(Project).where(Project.project_id==PROJECT_ID).with_for_update())
        if existing:
            if not reset: raise ValueError("Demo data already exists; no data changed. Use --reset-demo for this reserved project only.")
            if existing.description != MARKER: raise ValueError("Reserved project marker mismatch; reset refused.")
            s.execute(delete(Project).where(Project.project_id==PROJECT_ID))
            s.flush()
        s.add(Project(project_id=PROJECT_ID,name="Phase14 Canonical Demo",description=MARKER));s.flush()
        for platform in ("X","INSTAGRAM"):
            s.add(ProjectPlatform(project_platform_id=stable("platform:"+platform),project_id=PROJECT_ID,platform=platform))
        for platform,name,role in ACCOUNTS:
            s.add(SNSAccount(account_id=stable("account:"+name),project_id=PROJECT_ID,platform=platform,
                account_name=name,display_name="Fictional "+name,account_role=role))
        for name,keyword,hashtag in TOPICS:
            topic_id=stable("topic:"+name)
            s.add(WatchTopic(topic_id=topic_id,project_id=PROJECT_ID,topic_name=name));s.flush()
            for value,kind in ((keyword,"KEYWORD"),(hashtag,"HASHTAG")):
                s.add(WatchTerm(term_id=stable("term:"+value),topic_id=topic_id,term=value,
                    normalized_term=unicodedata.normalize("NFKC",value).casefold(),term_type=kind))

def load(factory, directory=None, anchor=ANCHOR, seed=SEED, reset=False):
    started=perf_counter()
    # Validate/generate all CSVs BEFORE touching existing project data.
    with tempfile.TemporaryDirectory(prefix="sns-demo-") as temp:
        generated=Path(temp)/"canonical"
        manifest=generate(generated,anchor,seed)
        source=Path(directory) if directory else generated
        for filename, info in manifest["files"].items():
            data=(source/filename).read_bytes()
            if hashlib.sha256(data).hexdigest()!=info["sha256"]: raise ValueError("Canonical CSV does not match anchor/seed/version")
        generation_seconds=perf_counter()-started
        setup(factory,reset)
        timer=TimedTrend()
        service=ImportService(factory,now_provider=lambda: datetime.combine(anchor,datetime.min.time(),timezone.utc),trend_service=timer)
        imports=[]
        for kind in (CsvDatasetType.OWN_POSTS,CsvDatasetType.COMPETITOR_POSTS,CsvDatasetType.ACCOUNT_DAILY,CsvDatasetType.TREND_POSTS):
            start=perf_counter()
            import_id,clock=service.start(PROJECT_ID,kind,FILES[kind])
            result=service.run(import_id,clock,PROJECT_ID,kind,source/FILES[kind])
            if result.status!="SUCCESS" or result.error_count: raise ValueError("Demo import failed; inspect reserved project's Import history")
            imports.append(dict(dataset=kind.value,status=result.status,rows=result.success_count,seconds=perf_counter()-start))
        client=DemoClient()
        insight=InsightService(factory,client).generate(PROJECT_ID,Filters(platform=None,start=date.fromisoformat(manifest["first_date"]),end=anchor))
        return dict(project_id=str(PROJECT_ID),manifest=manifest,imports=imports,ai_model=insight.model_name,
            fixture_calls=client.calls,live_openai_calls=0,generation_seconds=generation_seconds,
            trend_rebuild_seconds=timer.seconds,total_seconds=perf_counter()-started)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor-date",type=date.fromisoformat,default=ANCHOR)
    parser.add_argument("--seed",type=int,default=SEED)
    parser.add_argument("--directory",type=Path)
    parser.add_argument("--reset-demo",action="store_true",help="Delete/recreate ONLY reserved marked Phase14 Project")
    args=parser.parse_args()
    from app.db.session import SessionLocal
    try: result=load(SessionLocal,args.directory,args.anchor_date,args.seed,args.reset_demo)
    except ValueError as e: parser.exit(2,str(e)+"\n")
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
