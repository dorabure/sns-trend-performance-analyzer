from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4
import httpx
import pytest
from app.providers.core import ProviderContext, ProviderCredential, ProviderError, ProviderRegistry
from app.providers.http_client import ProviderHTTPClient
from app.providers.x_api_provider import XApiProvider, XProviderNormalizer

OBS = datetime(2026, 10, 4, 8, tzinfo=timezone.utc)
USER = {'data': {'id': '12345', 'username': 'test_own', 'name': 'Fixture', 'url': 'https://example.invalid',
    'public_metrics': {'followers_count': 0, 'following_count': 2, 'post_count': 7}}}


def post(pid='99', **changes):
    return dict({'id': pid, 'text': 'fixture #sample', 'created_at': '2026-10-04T01:00:00Z',
        'public_metrics': {'like_count': 10, 'reply_count': 2, 'repost_count': 3, 'quote_count': 1,
            'bookmark_count': 4, 'impression_count': 20}, 'entities': {'hashtags': [{'tag': 'sample'}]}}, **changes)


def context(previous=None):
    return ProviderContext(uuid4(), uuid4(), ProviderCredential('test-only-access'), OBS,
        last_remote_ids={'POSTS': previous})


def provider(responses):
    calls = []
    def mock(request):
        calls.append(request)
        response = responses[len(calls) - 1]
        return response if isinstance(response, httpx.Response) else httpx.Response(200, json=response)
    client = ProviderHTTPClient(transport=httpx.MockTransport(mock), sleep=lambda _: None, jitter=lambda: 0)
    return XApiProvider(client, enabled=lambda: True), calls


def test_registry_production_x_and_gated_instagram():
    remote, normalizer = ProviderRegistry().get('X_API')
    assert type(remote) is XApiProvider and type(normalizer) is XProviderNormalizer
    assert {str(c) for c in remote.capabilities()} == {'ACCOUNT_PROFILE', 'OWN_POSTS', 'OWN_METRICS'}
    instagram, _ = ProviderRegistry().get('INSTAGRAM_API')
    assert instagram.provider_type == 'INSTAGRAM_API'
    with pytest.raises(ProviderError, match='INSTAGRAM_LIVE_SMOKE_DISABLED'):
        instagram.validate_connection(ProviderCredential('test-only-token'))


@pytest.mark.parametrize('live,smoke', [('false', 'false'), ('true', 'false'), ('false', 'true')])
def test_default_double_gate_no_http(monkeypatch, live, smoke):
    monkeypatch.setenv('LIVE_MODE_ENABLED', live); monkeypatch.setenv('X_LIVE_SMOKE_ENABLED', smoke)
    remote = XApiProvider(ProviderHTTPClient(transport=httpx.MockTransport(lambda _: pytest.fail('network'))))
    with pytest.raises(ProviderError, match='X_LIVE_SMOKE_DISABLED'):
        remote.validate_connection(ProviderCredential('test-only-access'))


def test_validate_only_me_fields_no_posts(caplog):
    remote, calls = provider([USER])
    result = remote.validate_connection(context().credential)
    assert result.remote_account_id == '12345' and len(calls) == 1
    assert str(calls[0].url).split('?')[0] == 'https://api.x.com/2/users/me'
    assert dict(calls[0].url.params) == {'user.fields': remote.USER_FIELDS}
    assert not caplog.text


def test_initial_latest_five_one_page_and_metrics():
    remote, calls = provider([USER, {'data': [post('99'), post('100')], 'meta': {'next_token': 'ignored'}}])
    ctx = context(); account = remote.fetch_account(ctx); page = remote.fetch_posts(ctx, account)
    assert len(calls) == 2 and page.next_cursor is None and page.last_remote_id == '100'
    assert account.metrics.values == {'followers': 0, 'following': 2, 'post_count': 7}
    assert page.records[0].metrics.values == {'impressions': 20, 'likes': 10, 'comments': 2, 'shares': 4, 'saves': 4, 'reach': None, 'views': None}
    params = dict(calls[1].url.params)
    assert params == {'max_results': '5', 'exclude': 'replies,retweets', 'post.fields': remote.POST_FIELDS,
        'expansions': 'attachments.media_keys', 'media.fields': 'type,public_metrics'}
    assert page.records[0].metrics.observed_at == OBS and page.records[0].posted_at.tzinfo == timezone.utc
    assert page.records[0].permalink == 'https://x.com/test_own/status/99'
    assert page.records[0].hashtags == ['sample']


def test_incremental_collects_all_pages_numeric_id_and_clears_cursor():
    remote, calls = provider([{'data': [post('101')], 'meta': {'next_token': 'page2'}}, {'data': [post('100')]}])
    ctx = context('99'); account = remote.account(USER)
    page = remote.fetch_posts(ctx, account)
    assert [p.remote_post_id for p in page.records] == ['101', '100']
    assert page.last_remote_id == '101' and page.next_cursor is None
    assert dict(calls[0].url.params)['since_id'] == dict(calls[1].url.params)['since_id'] == '99'
    assert dict(calls[0].url.params)['max_results'] == '100'
    assert dict(calls[1].url.params)['pagination_token'] == 'page2'


@pytest.mark.parametrize('raw', [{}, {'data': []}, {'meta': {'result_count': 0}}])
@pytest.mark.parametrize('previous', [None, '99'])
def test_empty_preserves_previous_checkpoint(raw, previous):
    remote, _ = provider([raw]); page = remote.fetch_posts(context(previous), remote.account(USER))
    assert page.records == [] and page.last_remote_id == previous and page.next_cursor is None


@pytest.mark.parametrize('name,value', [('X_INITIAL_MAX_RESULTS', '4'), ('X_INITIAL_MAX_RESULTS', '101'),
    ('X_INCREMENTAL_PAGE_SIZE', '0'), ('X_INCREMENTAL_PAGE_SIZE', '101'), ('X_INCREMENTAL_MAX_PAGES', '0'),
    ('X_INCREMENTAL_MAX_PAGES', 'bad')])
def test_limits_reject_before_request(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    remote, calls = provider([])
    with pytest.raises(ProviderError, match='PROVIDER_BAD_REQUEST'):
        remote.fetch_posts(context(None if name == 'X_INITIAL_MAX_RESULTS' else '99'), remote.account(USER))
    assert calls == []


def test_page_cap_fails_without_partial_result(monkeypatch):
    monkeypatch.setenv('X_INCREMENTAL_MAX_PAGES', '2')
    remote, calls = provider([{'data': [post('102')], 'meta': {'next_token': 'p2'}},
        {'data': [post('101')], 'meta': {'next_token': 'p3'}}])
    with pytest.raises(ProviderError, match='PROVIDER_SYNC_LIMIT_EXCEEDED'):
        remote.fetch_posts(context('99'), remote.account(USER))
    assert len(calls) == 2


@pytest.mark.parametrize('kinds,expected', [([], 'TEXT'), (['photo'], 'IMAGE'), (['photo', 'photo'], 'CAROUSEL'),
    (['video'], 'VIDEO'), (['animated_gif'], 'VIDEO'), (['photo', 'video'], 'VIDEO'), (['audio'], 'OTHER'), ([None], 'OTHER')])
def test_media_normalizes(kinds, expected):
    remote, _ = provider([])
    keys = [str(i) for i in range(len(kinds))]
    raw = {'data': [post(attachments={'media_keys': keys})],
        'includes': {'media': [{'media_key': str(i), 'type': k} for i, k in enumerate(kinds) if k is not None]}}
    result = remote.parse_posts(raw, remote.account(USER), OBS)
    assert result[0].media_kind == expected
    assert str(XProviderNormalizer().normalize_posts(result, remote.account(USER))[0].media_type) == expected


@pytest.mark.parametrize('value', [None, 0])
def test_missing_and_zero_not_confused(value):
    remote, _ = provider([])
    metrics = {} if value is None else {k: 0 for k in ['like_count', 'reply_count', 'repost_count', 'quote_count', 'bookmark_count', 'impression_count']}
    dto = remote.parse_posts({'data': [post(public_metrics=metrics)]}, remote.account(USER), OBS)[0]
    assert all(v == value for k, v in dto.metrics.values.items() if k not in ('reach', 'views'))
    assert dto.metrics.values['reach'] is dto.metrics.values['views'] is None


@pytest.mark.parametrize('changes', [{'id': 'oops'}, {'id': 10}, {'created_at': '2026-10-04'},
    {'created_at': 'bad'}, {'public_metrics': []}, {'public_metrics': {'like_count': -1}},
    {'public_metrics': {'like_count': True}}, {'public_metrics': {'like_count': 1.5}}, {'text': None},
    {'entities': {'hashtags': ['bad']}}, {'attachments': {'media_keys': 'bad'}}])
def test_malformed_posts_rejected(changes):
    remote, _ = provider([])
    with pytest.raises(ProviderError, match='PROVIDER_RESPONSE_INVALID'):
        remote.parse_posts({'data': [post(**changes)]}, remote.account(USER), OBS)


@pytest.mark.parametrize('raw', [{'data': USER['data'], 'errors': [{'detail': 'test-only-private'}]}, {'data': None},
    {'data': {'id': 'abc', 'username': 'test'}}, {'data': {'id': '1', 'username': ''}},
    {'data': {'id': '1', 'username': 'test', 'public_metrics': None}}])
def test_bad_users_and_partial_error_fixed(raw, caplog):
    remote, _ = provider([raw])
    with pytest.raises(ProviderError, match='PROVIDER_RESPONSE_INVALID') as exc:
        remote.validate_connection(context().credential)
    assert 'test-only-private' not in str(exc.value) + caplog.text


@pytest.mark.parametrize('raw', [{'data': [post()], 'errors': [{'detail': 'private'}]}, {'data': None},
    {'meta': {'next_token': 1}}, {'meta': {'next_token': ''}}, {'includes': {'media': 'invalid'}}])
def test_bad_timeline_envelope(raw):
    remote, _ = provider([raw])
    with pytest.raises(ProviderError, match='PROVIDER_RESPONSE_INVALID'):
        remote.fetch_posts(context('90'), remote.account(USER))


def test_rate_reset_priority_and_numeric_header_allowlist(monkeypatch):
    monkeypatch.setattr('app.providers.http_client.time.time', lambda: 1000)
    calls, sleeps = [], []
    def mock(request):
        calls.append(1)
        return httpx.Response(429, headers={'x-rate-limit-reset': '1002', 'Retry-After': '999'}) if len(calls) == 1 else httpx.Response(200, json=USER,
            headers={'x-rate-limit-limit': '75', 'x-rate-limit-remaining': '74', 'x-rate-limit-reset': '1900', 'Authorization': 'private'})
    remote = XApiProvider(ProviderHTTPClient(transport=httpx.MockTransport(mock), sleep=sleeps.append), enabled=lambda: True)
    remote.validate_connection(context().credential)
    assert sleeps == [2] and remote.rate_metadata == {'rate_limit_remaining': 74, 'rate_limit_reset': 1900}


def test_long_rate_delay_no_sleep(monkeypatch):
    monkeypatch.setattr('app.providers.http_client.time.time', lambda: 1000)
    remote, calls = provider([httpx.Response(429, headers={'x-rate-limit-reset': '1061'})])
    with pytest.raises(ProviderError, match='PROVIDER_RATE_LIMITED'):
        remote.validate_connection(context().credential)
    assert len(calls) == 1


@pytest.mark.parametrize('value', ['-1', 'NaN', '1.5', 'private', '9' * 100])
def test_invalid_rate_metadata_discarded(value):
    client = ProviderHTTPClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={}, headers={'x-rate-limit-remaining': value})))
    assert client.get_response('https://api.x.com/2/users/me', context().credential).rate_limit_remaining is None
