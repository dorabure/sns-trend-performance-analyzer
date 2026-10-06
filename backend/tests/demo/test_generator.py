import json
import csv
import hashlib
from datetime import timedelta
from pathlib import Path
import pytest
from app.demo.generator import generate,ANCHOR,SEED,FILES
from app.providers.base import CsvDatasetType
from app.providers.csv_provider import CSVProvider
from app.providers.csv_schema import SCHEMAS

def test_determinism_and_canonical_manifest(tmp_path):
    one=generate(tmp_path/"one"/"canonical",ANCHOR,SEED)
    two=generate(tmp_path/"two"/"canonical",ANCHOR,SEED)
    assert one==two
    canonical=Path("/demo_data/canonical")
    if not canonical.exists(): canonical=Path(__file__).resolve().parents[3]/"demo_data/canonical"
    assert json.loads((canonical.parent/'manifest.json').read_text(encoding='utf-8'))==one
    for filename in FILES.values():
        data=(tmp_path/"one/canonical"/filename).read_bytes()
        assert data==(tmp_path/"two/canonical"/filename).read_bytes()==(canonical/filename).read_bytes()
    assert one["counts"]==dict(own_posts=180,account_daily=180,competitor_posts=540,trend_posts=4500)

@pytest.mark.parametrize("kind",list(CsvDatasetType))
def test_schema_encoding_counts_ids_no_secret_and_provider(tmp_path,kind):
    manifest=generate(tmp_path/"canonical",ANCHOR,SEED)
    path=tmp_path/"canonical"/FILES[kind]
    data=path.read_bytes(); text=data.decode("utf-8")
    assert len(data)<20971520 and "sk-" not in text and "@" not in text
    with path.open(encoding="utf-8",newline="") as f:
        reader=csv.DictReader(f);assert tuple(reader.fieldnames)==SCHEMAS[kind].headers;rows=list(reader)
    assert len(rows)==manifest["counts"][kind.value.lower()]
    assert {r["platform"] for r in rows}=={"X","INSTAGRAM"}
    if kind!=CsvDatasetType.ACCOUNT_DAILY: assert len({r['post_id'] for r in rows})==len(rows)
    parsed=CSVProvider().read(path,kind)
    assert parsed.total_rows==parsed.valid_rows==len(rows) and not parsed.errors

@pytest.mark.parametrize("anchor,seed",[(ANCHOR-timedelta(days=30),SEED),(ANCHOR,SEED+1)])
def test_explicit_anchor_and_seed_change_output(tmp_path,anchor,seed):
    first=generate(tmp_path/"one/canonical",ANCHOR,SEED)
    second=generate(tmp_path/"two/canonical",anchor,seed)
    assert first!=second and second['anchor_date']==anchor.isoformat() and second['seed']==seed
    assert second['counts']==first['counts']
