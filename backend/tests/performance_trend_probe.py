"""Supplemental unchanged timeseries path, original Phase11 vs current Source.

Use PYTHONPATH for the original app package; do not replace running app files.
This is a separate reference comparison collected after primary optimization.
"""
import json
import hashlib
import inspect
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db.models import WatchTerm, WatchTopic
from app.services.my_account_service import MyAccountService
from app.services.trend_explorer_service import TrendExplorerService
from tests.performance_probe import analyze, blocked, canonical, large_fixture, probe
from tests.postgres_support import disposable_database, migrate


def main():
    module_path = Path(inspect.getfile(TrendExplorerService))
    if sys.argv[1] == 'phase11_original':
        assert '/phase12_reference/' in str(module_path)
    else:
        assert str(module_path).startswith('/app/app/')
    httpx.HTTPTransport.handle_request = blocked
    httpx.AsyncHTTPTransport.handle_async_request = blocked
    output, plans = {}, []
    for size in [None, 100, 1000, 2000]:
        with disposable_database() as engine:
            migrate(engine, 'upgrade', 'head')
            pid = canonical(engine) if size is None else large_fixture(engine, size)[0]
            analyze(engine)
            factory = sessionmaker(engine, expire_on_commit=False)
            with factory() as s:
                ids = list(s.scalars(select(WatchTerm.term_id).join(WatchTopic).where(
                    WatchTopic.project_id == pid, WatchTopic.is_active.is_(True), WatchTerm.is_active.is_(True))
                    .order_by(WatchTerm.term_id).limit(5)))
            filters = MyAccountService.filters(date(2026,7,7) if size is None else date(2026,10,1),
                date(2026,10,4) if size is None else date(2026,10,3))
            service = TrendExplorerService(factory)
            probe(engine, 'canonical_timeseries' if size is None else f'own{size}_timeseries',
                lambda: service.timeseries(pid, ids, filters, 'trend_score'), output, plans)
    Path(sys.argv[2]).write_text(json.dumps(dict(reference=sys.argv[1],
        timestamp=datetime.now(timezone.utc).isoformat(), warmup=1, measured_runs=5,
        comparison_kind='supplemental original-source vs current-source; unchanged timeseries',
        external_http_calls=0, timeseries_service_sha256=hashlib.sha256(module_path.read_bytes()).hexdigest(),
        operations=output), ensure_ascii=False, indent=2))
    Path(sys.argv[2] + '.plans.json').write_text(json.dumps(plans, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
