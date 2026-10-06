"""Read-only own-account X API v2. No persistence or alternative endpoints."""
import os
import re
from datetime import datetime, timezone
from app.core.live_operations import live_enabled
from app.providers.core import (ProviderAccountDTO, ProviderPostDTO, ProviderMetricDTO,
    ProviderPage, ProviderCapability, ProviderValidationResult, ProviderError)
from app.providers.http_client import ProviderHTTPClient
from app.providers.normalizer import DTOProviderNormalizer


def flag(name):
    return os.getenv(name, 'false').strip().lower() == 'true'


def x_live_enabled():
    return live_enabled() and flag('X_LIVE_SMOKE_ENABLED')


def integer_setting(name, default, minimum, maximum):
    try:
        raw = os.getenv(name, str(default))
        if not re.fullmatch(r'[0-9]+', raw):
            raise ValueError()
        value = int(raw)
        if not minimum <= value <= maximum:
            raise ValueError()
        return value
    except (ValueError, TypeError):
        raise ProviderError('PROVIDER_BAD_REQUEST') from None


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,19}', value):
        raise ProviderError('PROVIDER_RESPONSE_INVALID')
    return value


def utc_datetime(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.utcoffset() is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except Exception:
        raise ProviderError('PROVIDER_RESPONSE_INVALID') from None


def mapping(value):
    if not isinstance(value, dict):
        raise ProviderError('PROVIDER_RESPONSE_INVALID')
    return value


def metric(raw, key):
    value = raw.get(key)
    if value is not None and (type(value) is not int or value < 0):
        raise ProviderError('PROVIDER_RESPONSE_INVALID')
    return value


class XProviderNormalizer(DTOProviderNormalizer):
    def __init__(self):
        super().__init__('X_API')


class XApiProvider:
    provider_type = 'X_API'
    USER_FIELDS = 'id,username,name,url,profile_image_url,public_metrics'
    POST_FIELDS = 'created_at,public_metrics,entities,attachments'

    def __init__(self, client=None, *, enabled=None):
        self.client = client or ProviderHTTPClient()
        self.enabled = enabled or x_live_enabled
        self.rate_metadata = {}

    def guard(self):
        if not self.enabled():
            raise ProviderError('X_LIVE_SMOKE_DISABLED')

    def capabilities(self):
        return {ProviderCapability.ACCOUNT_PROFILE, ProviderCapability.OWN_POSTS, ProviderCapability.OWN_METRICS}

    def get(self, path, credential, params, heartbeat=lambda: None):
        self.guard()
        response = self.client.get_response('https://api.x.com' + path, credential, params=params, heartbeat=heartbeat)
        self.rate_metadata = {key: value for key, value in (
            ('rate_limit_remaining', response.rate_limit_remaining), ('rate_limit_reset', response.rate_limit_reset)) if value is not None}
        raw = mapping(response.data)
        if raw.get('errors'):
            raise ProviderError('PROVIDER_RESPONSE_INVALID')
        return raw

    def account(self, raw, observed=None):
        data = mapping(raw.get('data'))
        remote_id = identifier(data.get('id'))
        username = data.get('username')
        if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,100}', username):
            raise ProviderError('PROVIDER_RESPONSE_INVALID')
        for name in ('name', 'url'):
            if data.get(name) is not None and not isinstance(data[name], str):
                raise ProviderError('PROVIDER_RESPONSE_INVALID')
        metrics = mapping(data.get('public_metrics', {}))
        return ProviderAccountDTO(remote_id, username, data.get('name'), data.get('url'), observed,
            ProviderMetricDTO({target: metric(metrics, source) for target, source in (
                ('followers', 'followers_count'), ('following', 'following_count'), ('post_count', 'post_count'))}, observed))

    def validate_connection(self, credential):
        account = self.account(self.get('/2/users/me', credential, {'user.fields': self.USER_FIELDS}))
        return ProviderValidationResult(account.remote_account_id, self.capabilities())

    def fetch_account(self, context):
        return self.account(self.get('/2/users/me', context.credential, {'user.fields': self.USER_FIELDS}, context.heartbeat), context.observation_time)

    def parse_posts(self, raw, account, observed):
        records = raw.get('data', [])
        if not isinstance(records, list):
            raise ProviderError('PROVIDER_RESPONSE_INVALID')
        includes = mapping(raw.get('includes', {}))
        media = includes.get('media', [])
        if not isinstance(media, list):
            raise ProviderError('PROVIDER_RESPONSE_INVALID')
        by_key = {}
        for item in media:
            item = mapping(item)
            if not isinstance(item.get('media_key'), str) or not isinstance(item.get('type'), str):
                raise ProviderError('PROVIDER_RESPONSE_INVALID')
            by_key[item['media_key']] = item['type']
        result = []
        for item in records:
            item = mapping(item)
            post_id = identifier(item.get('id'))
            if 'author_id' in item and item['author_id'] != account.remote_account_id:
                raise ProviderError('PROVIDER_SCOPE_INVALID')
            if not isinstance(item.get('text'), str):
                raise ProviderError('PROVIDER_RESPONSE_INVALID')
            metrics = mapping(item.get('public_metrics', {}))
            values = {target: metric(metrics, source) for target, source in (
                ('impressions', 'impression_count'), ('likes', 'like_count'), ('comments', 'reply_count'), ('saves', 'bookmark_count'))}
            repost, quote = metric(metrics, 'repost_count'), metric(metrics, 'quote_count')
            values.update(shares=None if repost is None or quote is None else repost + quote, reach=None, views=None)
            keys = mapping(item.get('attachments', {})).get('media_keys', [])
            if not isinstance(keys, list) or any(not isinstance(k, str) for k in keys):
                raise ProviderError('PROVIDER_RESPONSE_INVALID')
            types = [by_key.get(k) for k in keys]
            kind = 'TEXT' if not keys else 'VIDEO' if any(t in ('video', 'animated_gif') for t in types) else ('IMAGE' if len(keys) == 1 else 'CAROUSEL') if all(t == 'photo' for t in types) else 'OTHER'
            hashtags = mapping(item.get('entities', {})).get('hashtags', [])
            if not isinstance(hashtags, list) or any(not isinstance(h, dict) or not isinstance(h.get('tag'), str) or not h['tag'] for h in hashtags):
                raise ProviderError('PROVIDER_RESPONSE_INVALID')
            result.append(ProviderPostDTO(post_id, account.remote_account_id, utc_datetime(item.get('created_at')),
                item['text'], kind, f'https://x.com/{account.username}/status/{post_id}',
                ProviderMetricDTO(values, observed), [h['tag'] for h in hashtags], {'id': post_id, 'media_kind': kind}))
        return result

    def fetch_posts(self, context, account):
        self.guard()
        remote_id = identifier(account.remote_account_id)
        previous = context.last_remote_ids.get('POSTS')
        if previous is not None:
            identifier(previous)
        initial = previous is None
        page_size = integer_setting('X_INITIAL_MAX_RESULTS' if initial else 'X_INCREMENTAL_PAGE_SIZE', 5 if initial else 100, 5, 100)
        max_pages = 1 if initial else integer_setting('X_INCREMENTAL_MAX_PAGES', 5, 1, 100)
        params = {'max_results': page_size, 'exclude': 'replies,retweets', 'post.fields': self.POST_FIELDS,
            'expansions': 'attachments.media_keys', 'media.fields': 'type,public_metrics'}
        if previous:
            params['since_id'] = previous
        all_posts, seen_tokens = [], set()
        for page_index in range(max_pages):
            raw = self.get(f'/2/users/{remote_id}/tweets', context.credential, params, context.heartbeat)
            posts = self.parse_posts(raw, account, context.observation_time)
            if len(posts) > page_size or previous and any(int(p.remote_post_id) <= int(previous) for p in posts):
                raise ProviderError('PROVIDER_RESPONSE_INVALID')
            all_posts.extend(posts)
            next_token = mapping(raw.get('meta', {})).get('next_token')
            if next_token is not None and (not isinstance(next_token, str) or not next_token or len(next_token) > 4096):
                raise ProviderError('PROVIDER_RESPONSE_INVALID')
            if initial or not next_token:
                ids = [p.remote_post_id for p in all_posts] + ([previous] if previous else [])
                return ProviderPage(all_posts, None, max(ids, key=int) if ids else None)
            if page_index == max_pages - 1:
                raise ProviderError('PROVIDER_SYNC_LIMIT_EXCEEDED')
            if next_token in seen_tokens:
                raise ProviderError('PROVIDER_RESPONSE_INVALID')
            seen_tokens.add(next_token)
            params['pagination_token'] = next_token
