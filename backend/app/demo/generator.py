"""Deterministic UTF-8 CSV generation using existing provider schemas."""
import argparse
import csv
import hashlib
import json
import math
import random
import re
from datetime import date, timedelta
from pathlib import Path
from app.providers.base import CsvDatasetType
from app.providers.csv_schema import SCHEMAS

VERSION = "phase14-v1"
ANCHOR = date(2026, 10, 4)
SEED = 1401
TOPICS = (
    ("生成AI", "生成AI研究", "#生成AI研究"),
    ("業務効率化", "効率化実験", "#効率化実験"),
    ("AIエージェント", "エージェント検証", "#エージェント検証"),
    ("データ分析", "分析ノート", "#分析ノート"),
    ("動画生成", "動画ラボ", "#動画ラボ"),
    ("SNS運用", "運用メモ", "#運用メモ"),
)
ACCOUNTS = (("X", "demo_own_x", "OWN"), ("INSTAGRAM", "demo_own_instagram", "OWN"),
    ("X", "demo_competitor_x_01", "COMPETITOR"), ("X", "demo_competitor_x_02", "COMPETITOR"),
    ("INSTAGRAM", "demo_competitor_instagram_01", "COMPETITOR"))
FILES = {kind: kind.value.lower() + ".csv" for kind in CsvDatasetType}
FILES[CsvDatasetType.TREND_POSTS] = "trend_posts.csv"


def weights(day):
    # Distinct phases; last three windows give rising, peak, falling, stable,
    # low, and renewed-growth distributions. Scores are computed by TrendEngine.
    base = [7, 8, 13, 10, 3, 9]
    if day < 60:
        return [max(1, b + round(3 * math.sin((day - k * 8) / 10))) for k,b in enumerate(base)]
    t = day - 60
    return [7 + t*t/20, 9 + t*t/25, max(2, 20-t*.6), 10, 2, 6 + max(0,t-12)*.65]


def generate(output: Path, anchor=ANCHOR, seed=SEED):
    rng = random.Random(seed)
    output.mkdir(parents=True, exist_ok=True)
    rows = {kind: [] for kind in CsvDatasetType}
    first = anchor - timedelta(days=89)
    for day in range(90):
        current = first + timedelta(days=day)
        stamp = current.isoformat() + "T12:00:00Z"
        for account_index,(platform,name,_) in enumerate(ACCOUNTS[:2]):
            # All own posts cover data analysis; efficiency coverage >50%,
            # rising AI coverage <50%. Multiple topic matches are intentional.
            topics = [3] + ([1] if day % 4 != 0 else []) + ([0] if day % 10 == 0 else [])
            text = "架空デモ " + " / ".join(TOPICS[t][1] for t in topics) + " 日本語 ✨"
            media = (["TEXT","IMAGE","VIDEO","CAROUSEL"] if platform == "X" else ["IMAGE","VIDEO","CAROUSEL","TEXT"])[day % 4]
            values = dict(impressions=600+day*4, reach=400+day*3, views=200+day*2,
                likes=18+day%15+account_index*8, comments=3+day%4, shares=2+day%3, saves=1+day%5)
            if day == 86: values = {key: 0 for key in values}
            if day == 87: values = {key: "" for key in values}
            hashtags = "" if day % 5 == 0 else ";".join(TOPICS[t][2] for t in topics)
            rows[CsvDatasetType.OWN_POSTS].append(dict(platform=platform,post_id=f"demo-own-{account_index}-{day:03}",
                account_name=name,posted_at=stamp,text=text,media_type=media,hashtags=hashtags,**values))
            rows[CsvDatasetType.ACCOUNT_DAILY].append(dict(platform=platform,account_name=name,date=current.isoformat(),
                followers=(1200+day*3 if platform=="X" else 800+day*3),following=100+day//15,post_count=day+1))
        for idx,(platform,name,_) in enumerate(ACCOUNTS[2:]):
            for post in range((3,2,1)[idx]):
                t = (day + post + idx*2) % 6
                rows[CsvDatasetType.COMPETITOR_POSTS].append(dict(platform=platform,account_name=name,
                    post_id=f"demo-comp-{idx}-{day:03}-{post}",posted_at=stamp,text=f"架空競合 {TOPICS[t][1]} ✨",
                    media_type=("VIDEO" if idx==2 else ["TEXT","IMAGE"][post%2]), views=900+idx*200,
                    likes=(30,80,55)[idx]+day%12,comments=6+idx*2,shares=4+idx,followers=(2400,1700,950)[idx]+day*(idx+1)))
        distribution = weights(day)
        allocations = [int(50*w/sum(distribution)) for w in distribution]
        for k in sorted(range(6),key=lambda k: -(50*distribution[k]/sum(distribution)-allocations[k]))[:50-sum(allocations)]:
            allocations[k] += 1
        for t,count in enumerate(allocations):
            for p in range(count):
                platform = "X" if p%2==0 else "INSTAGRAM"
                intensity = (80+max(0,day-60)*5 if t in (0,1) else max(12,100-day) if t==2 else 25 if t==3 else 5 if t==4 else 30+max(0,day-72)*2)
                rows[CsvDatasetType.TREND_POSTS].append(dict(platform=platform,post_id=f"demo-market-{day:03}-{t}-{p:02}",
                    posted_at=stamp,text=f"架空市場 {TOPICS[t][1]}",keyword=TOPICS[t][1],hashtags=TOPICS[t][2],
                    views=intensity*20,likes=intensity+rng.randrange(4),comments=intensity//8,shares=intensity//10))
    manifest = dict(version=VERSION,anchor_date=anchor.isoformat(),first_date=first.isoformat(),seed=seed,
        counts={},files={},topics=[t[0] for t in TOPICS],competitor_accounts=3,
        scenarios=["rising","peak","falling","stable","low","renewed_growth"],
        expected_contracts={"gap_classifications":["OPPORTUNITY","BALANCED","HIGH_COVERAGE","LOW_PRIORITY"],
            "null_and_zero":True,"ai":"Fixed fictional fixture; no live OpenAI calls"})
    for kind,records in rows.items():
        path=output/FILES[kind]
        with path.open("w",encoding="utf-8",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=SCHEMAS[kind].headers,lineterminator="\n")
            writer.writeheader();writer.writerows(records)
        data=path.read_bytes()
        if len(data)>20971520 or re.search(rb"sk-(?:proj-)?[A-Za-z0-9_-]{24,}",data):
            raise ValueError("Demo output failed size/secret validation")
        with path.open(encoding="utf-8",newline="") as f:
            reader=csv.reader(f)
            assert tuple(next(reader))==SCHEMAS[kind].headers
            assert sum(1 for _ in reader)==len(records)
        key=kind.value.lower()
        manifest["counts"][key]=len(records)
        manifest["files"][FILES[kind]]=dict(rows=len(records),bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),headers=list(SCHEMAS[kind].headers))
    (output.parent/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor-date",type=date.fromisoformat,default=ANCHOR)
    parser.add_argument("--seed",type=int,default=SEED)
    parser.add_argument("--output",type=Path,default=Path("/demo_data/canonical"))
    args=parser.parse_args()
    print(json.dumps(generate(args.output,args.anchor_date,args.seed),ensure_ascii=False,indent=2))

if __name__=="__main__": main()
