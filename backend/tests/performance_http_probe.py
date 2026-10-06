"""Read-only canonical HTTP timings; accepts only the normal localhost port."""
import hashlib
import json
import statistics
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


def main():
    # Explicit IPv4 avoids measuring Windows localhost IPv6 fallback as SQL latency.
    base = 'http://127.0.0.1:18000/api/v1'
    def get(path):
        with urllib.request.urlopen(base + path, timeout=60) as response:
            assert response.status == 200
            return response.read()
    projects = json.loads(get('/projects'))
    project = next(p for p in projects if p['name'] == 'Phase14 Canonical Demo')
    assert project['data_mode'] == 'DEMO'
    prefix = '/projects/' + project['project_id']
    params = urllib.parse.urlencode({'platform':'ALL','from':'2026-07-07','to':'2026-10-04'})
    accounts = json.loads(get(prefix + '/accounts'))
    ids = ','.join(a['account_id'] for a in accounts if a['account_role'] == 'COMPETITOR' and a['is_active'])
    topics = json.loads(get(prefix + '/topics'))
    topic = topics[0]['topic_id']
    paths = {'overview':'/dashboard/overview', 'own_analytics':'/accounts/own/analytics',
        'own_list':'/accounts/own/posts', 'gap':'/gap-analysis',
        'competitor':'/competitors/analytics', 'ranking':'/trends/ranking',
        'history_first':'/insights/history'}
    results = {}
    for name, path in paths.items():
        suffix = '&account_ids=' + ids if name == 'competitor' else '&topic_id=' + topic if name == 'ranking' else ''
        url = prefix + path + '?' + params + suffix
        get(url)
        samples = []
        for _ in range(5):
            started = time.perf_counter()
            raw = get(url)
            samples.append((time.perf_counter() - started) * 1000)
        results[name] = dict(runs_ms=samples, min_ms=min(samples), median_ms=statistics.median(samples),
            max_ms=max(samples), response_bytes=len(raw), http_status=200,
            golden_sha256=hashlib.sha256(json.dumps(json.loads(raw), sort_keys=True).encode()).hexdigest())
    Path(sys.argv[1]).write_text(json.dumps(dict(warmup=1, measured_runs=5, operations=results), indent=2))
    print(json.dumps({n:round(r['median_ms'],2) for n,r in results.items()}))


if __name__ == '__main__':
    main()
