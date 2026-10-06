"""Instagram Login profile adapter; media sync is blocked by official spec gaps.

Official sources and the unresolved product-type contract are recorded in the
Phase 7 report. Do not infer FEED/REELS/STORY from IMAGE/VIDEO or numeric IDs.
"""
import os
import re
from app.core.live_operations import live_enabled
from app.providers.core import (ProviderError, ProviderCapability, ProviderAccountDTO,
    ProviderMetricDTO, ProviderValidationResult)
from app.providers.http_client import ProviderHTTPClient
from app.providers.normalizer import DTOProviderNormalizer


def flag(name):
    return os.getenv(name, 'false').strip().lower() == 'true'


def instagram_live_enabled():
    return live_enabled() and flag('INSTAGRAM_LIVE_SMOKE_ENABLED')


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,32}', value):
        raise ProviderError('PROVIDER_RESPONSE_INVALID')
    return value


def mapping(value):
    if not isinstance(value, dict):
        raise ProviderError('PROVIDER_RESPONSE_INVALID')
    return value


def graph_version():
    # v26.0 is corroborated by Meta SDK; endpoint reference still says v25.0.
    # Require an explicit pin. Endpoint-version coverage remains a report gap.
    version = os.getenv('INSTAGRAM_GRAPH_API_VERSION', '')
    if not re.fullmatch(r'v[0-9]{1,3}\.0', version):
        raise ProviderError('PROVIDER_NOT_CONFIGURED')
    return version


class InstagramProviderNormalizer(DTOProviderNormalizer):
    def __init__(self):
        super().__init__('INSTAGRAM_API', {'IMAGE': 'IMAGE', 'VIDEO': 'VIDEO',
            'CAROUSEL_ALBUM': 'CAROUSEL'})


class InstagramApiProvider:
    provider_type = 'INSTAGRAM_API'
    PROFILE_FIELDS = 'user_id,username,name,account_type,followers_count,follows_count,media_count'

    def __init__(self, client=None, *, enabled=None):
        self.client = client or ProviderHTTPClient()
        self.enabled = enabled or instagram_live_enabled

    def capabilities(self):
        # Advertise only implemented operations; planned media/insights are not
        # available until their official contracts and implementation are ready.
        return {ProviderCapability.ACCOUNT_PROFILE}

    def guard(self):
        if not self.enabled():
            raise ProviderError('INSTAGRAM_LIVE_SMOKE_DISABLED')

    @staticmethod
    def account(raw, observed=None):
        raw = mapping(raw)
        if raw.get('error') or raw.get('errors'):
            raise ProviderError('PROVIDER_RESPONSE_INVALID')
        # Get Started documents a one-item data envelope; Graph also returns the
        # selected object directly. Both shapes require the canonical user_id.
        if 'data' in raw:
            if not isinstance(raw['data'], list) or len(raw['data']) != 1:
                raise ProviderError('PROVIDER_RESPONSE_INVALID')
            raw = mapping(raw['data'][0])
        remote_id = identifier(raw.get('user_id'))
        username = raw.get('username')
        if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_.]{1,30}', username):
            raise ProviderError('PROVIDER_RESPONSE_INVALID')
        kind = raw.get('account_type')
        if not isinstance(kind, str) or kind.upper() not in ('BUSINESS', 'MEDIA_CREATOR'):
            raise ProviderError('PROVIDER_SCOPE_INVALID')
        name = raw.get('name')
        if name is not None and not isinstance(name, str):
            raise ProviderError('PROVIDER_RESPONSE_INVALID')
        values = {target: raw.get(source) for target, source in (
            ('followers', 'followers_count'), ('following', 'follows_count'), ('post_count', 'media_count'))}
        return ProviderAccountDTO(remote_id, username, name,
            'https://www.instagram.com/' + username + '/', observed, ProviderMetricDTO(values, observed))

    def profile(self, credential, observed=None, heartbeat=lambda: None):
        self.guard()
        raw = self.client.get_json('https://graph.instagram.com/' + graph_version() + '/me',
            credential, params={'fields': self.PROFILE_FIELDS}, heartbeat=heartbeat)
        return self.account(raw, observed)

    def validate_connection(self, credential):
        account = self.profile(credential)
        return ProviderValidationResult(account.remote_account_id, self.capabilities())

    def fetch_account(self, context):
        return self.profile(context.credential, context.observation_time, context.heartbeat)

    def ensure_sync_ready(self):
        self.guard()
        raise ProviderError('INSTAGRAM_SPEC_UNVERIFIED')

    def fetch_posts(self, context, account):
        # No media list, insights request, import, or checkpoint may proceed
        # while the Instagram Login product-type contract is unverified.
        self.ensure_sync_ready()
