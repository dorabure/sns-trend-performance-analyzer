import csv
from io import StringIO

from app.providers.base import CsvDatasetType
from app.providers.csv_schema import SCHEMAS


def row(dataset, **overrides):
    values = dict.fromkeys(SCHEMAS[dataset].headers, "")
    values.update(platform="X", account_name="dummy_demo", post_id="p1", posted_at="2026-10-01T18:30:00+09:00", date="2026-10-01")
    values.update(overrides)
    return {key: values[key] for key in SCHEMAS[dataset].headers} | overrides


def csv_text(dataset, rows=None, headers=None):
    headers = list(SCHEMAS[dataset].headers) if headers is None else headers
    stream = StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(headers)
    for values in rows if rows is not None else [row(dataset)]:
        writer.writerow([values.get(name.strip(), "") for name in headers])
    return stream.getvalue()
