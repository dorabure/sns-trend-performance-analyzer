"""Explicit test fixtures only: never imported by app/ or production registry."""
from datetime import datetime, timezone
from app.providers.core import (ProviderAccountDTO, ProviderPostDTO, ProviderMetricDTO, ProviderPage,
    ProviderCapability, ProviderValidationResult, ProviderError)
from app.providers.normalizer import DTOProviderNormalizer

OBSERVED = datetime(2026, 10, 4, 8, tzinfo=timezone.utc)


class MockXProvider:
    provider_type = 'X_API'
    def __init__(self, observation=OBSERVED, failure=None):
        self.observation, self.failure = observation, failure
        self.calls = 0

    def capabilities(self):
        return {ProviderCapability.ACCOUNT_PROFILE, ProviderCapability.OWN_POSTS, ProviderCapability.OWN_METRICS}

    def validate_connection(self, credential):
        self.calls += 1
        if self.failure:
            raise ProviderError(self.failure)
        return ProviderValidationResult('remote-account', self.capabilities())

    def fetch_account(self, context):
        self.calls += 1
        if self.failure:
            raise ProviderError(self.failure)
        return ProviderAccountDTO('remote-account', 'mock-own', observed_at=self.observation,
            metrics=ProviderMetricDTO({'followers': 0, 'following': None, 'post_count': 2}))

    def fetch_posts(self, context, account):
        self.calls += 1
        return ProviderPage([ProviderPostDTO(str(i), 'remote-account', OBSERVED, text='test topic #sample',
            metrics=ProviderMetricDTO({'likes': i, 'reach': None}), hashtags=['sample']) for i in range(2)], 'next-page', '1')

    def normalizer(self):
        return DTOProviderNormalizer(self.provider_type)


class MockInstagramProvider(MockXProvider):
    provider_type = 'INSTAGRAM_API'

    def fetch_posts(self, context, account):
        self.calls += 1
        # Instagram-shaped media fields are parsed into DTOs at the provider boundary.
        raw = [{'id': 'ig-0', 'caption': 'test topic #sample', 'media_type': 'PHOTO', 'like_count': 0},
               {'id': 'ig-1', 'caption': 'test topic', 'media_type': 'ALBUM', 'like_count': 1}]
        return ProviderPage([ProviderPostDTO(r['id'], 'remote-account', OBSERVED, text=r['caption'],
            media_kind=r['media_type'], metrics=ProviderMetricDTO({'likes': r['like_count']}), safe_raw=r) for r in raw], 'ig-next', 'ig-1')

    def normalizer(self):
        return DTOProviderNormalizer(self.provider_type, {'PHOTO': 'IMAGE', 'ALBUM': 'CAROUSEL'})
