"""Check local Markdown / HTML links and canonical CSV integrity. No network I/O.

Run from any directory: python docs/portfolio/check_docs.py
Only repository documentation is checked; fenced example commands are ignored.
"""
from pathlib import Path
from urllib.parse import unquote
import csv
import hashlib
import io
import json
import re

ROOT = Path(__file__).resolve().parents[2]


def check():
    docs = [ROOT / 'README.md', ROOT / 'README_EN.md', ROOT / 'demo_data/README.md']
    docs += sorted((ROOT / 'docs').rglob('*.md'))
    checked, missing = 0, []
    for path in docs:
        text = re.sub(r'```[^\n]*\n.*?```', '', path.read_text(encoding='utf-8-sig'), flags=re.S)
        links = re.findall(r'\]\(([^\s)]+)(?:\s+"[^"]*")?\)', text)
        links += re.findall(r'(?:src|href)="([^"]+)"', text)
        for link in links:
            if re.match(r'[a-zA-Z][\w+.-]*:', link) or link.startswith('#'):
                continue
            local = unquote(link.split('#')[0].split('?')[0].strip('<>'))
            if not local:
                continue
            checked += 1
            if not (path.parent / local).exists():
                missing.append({'file': str(path.relative_to(ROOT)), 'target': local})
    manifest = json.loads((ROOT / 'demo_data/manifest.json').read_text(encoding='utf-8-sig'))
    files = []
    for name, expected in manifest['files'].items():
        data = (ROOT / 'demo_data/canonical' / name).read_bytes()
        rows = list(csv.reader(io.StringIO(data.decode('utf-8-sig'))))
        assert hashlib.sha256(data).hexdigest() == expected['sha256'], name
        assert len(data) == expected['bytes'], name
        assert len(rows) - 1 == expected['rows'], name
        assert rows[0] == expected['headers'], name
        files.append({'name': name, 'rows': len(rows) - 1, 'sha256': expected['sha256']})
    result = {'markdown_files': len(docs), 'local_links_checked': checked,
              'missing_links': missing, 'canonical_files': files}
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return not missing


if __name__ == '__main__':
    raise SystemExit(0 if check() else 1)
