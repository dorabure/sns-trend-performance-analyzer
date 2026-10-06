from dataclasses import dataclass

from app.providers.base import CsvDatasetType


@dataclass(frozen=True)
class CsvSchema:
    headers: tuple[str, ...]


SCHEMAS = {
    CsvDatasetType.OWN_POSTS: CsvSchema(tuple("platform post_id account_name posted_at text media_type impressions reach views likes comments shares saves hashtags".split())),
    CsvDatasetType.ACCOUNT_DAILY: CsvSchema(tuple("platform account_name date followers following post_count".split())),
    CsvDatasetType.TREND_POSTS: CsvSchema(tuple("platform post_id posted_at text keyword hashtags views likes comments shares".split())),
    CsvDatasetType.COMPETITOR_POSTS: CsvSchema(tuple("platform account_name post_id posted_at text media_type views likes comments shares followers".split())),
}
