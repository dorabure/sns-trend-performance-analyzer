"""External provider contracts, independent of the V1 CSV DataProvider."""
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Generic, Protocol, TypeVar
from uuid import UUID

from app.core.provider_metadata import safe_metadata
from app.dto.normalized import NormalizedPost, NormalizedAccountMetric


class ProviderCapability(StrEnum):
    ACCOUNT_PROFILE = 'ACCOUNT_PROFILE'
    OWN_POSTS = 'OWN_POSTS'
    OWN_METRICS = 'OWN_METRICS'
    MARKET_POSTS = 'MARKET_POSTS'
    COMPETITOR_POSTS = 'COMPETITOR_POSTS'
    TREND_DATA = 'TREND_DATA'


def checked_capabilities(values):
    if not isinstance(values, (list, set, frozenset, tuple)):
        raise ValueError('Invalid provider capabilities')
    try:
        result = [ProviderCapability(v) for v in values]
    except (ValueError, TypeError):
        raise ValueError('Invalid provider capabilities') from None
    if len(result) != len(set(result)):
        raise ValueError('Duplicate provider capabilities')
    return sorted(v.value for v in result)


ERROR_CODES = frozenset('PROVIDER_NOT_IMPLEMENTED PROVIDER_NOT_CONFIGURED PROVIDER_AUTH_FAILED PROVIDER_PERMISSION_DENIED PROVIDER_RATE_LIMITED PROVIDER_TIMEOUT PROVIDER_NETWORK_ERROR PROVIDER_BAD_REQUEST PROVIDER_SERVER_ERROR PROVIDER_RESPONSE_INVALID PROVIDER_CAPABILITY_UNAVAILABLE SECRET_STORE_UNAVAILABLE LIVE_MODE_DISABLED PROVIDER_NOT_READY PROVIDER_SCOPE_INVALID PROVIDER_IMPORT_FAILED PROVIDER_CHECKPOINT_FAILED'.split())


ERROR_CODES = ERROR_CODES | frozenset('PROVIDER_SYNC_LIMIT_EXCEEDED X_LIVE_SMOKE_DISABLED X_LIVE_REFRESH_DISABLED OAUTH_DISABLED OAUTH_STATE_INVALID OAUTH_STATE_EXPIRED OAUTH_PROVIDER_INVALID OAUTH_TOKEN_EXCHANGE_FAILED OAUTH_SCOPE_INSUFFICIENT'.split())
ERROR_CODES = ERROR_CODES | frozenset('INSTAGRAM_LIVE_SMOKE_DISABLED INSTAGRAM_LIVE_REFRESH_DISABLED INSTAGRAM_REFRESH_TOO_EARLY INSTAGRAM_REAUTH_REQUIRED INSTAGRAM_SPEC_UNVERIFIED'.split())


class ProviderError(Exception):
    def __init__(self, code, *, retryable=False, retry_after_seconds=None):
        self.code = code if code in ERROR_CODES else 'PROVIDER_RESPONSE_INVALID'
        self.retryable = bool(retryable)
        self.retry_after_seconds = retry_after_seconds
        super().__init__(self.code)


@dataclass(frozen=True, eq=False)
class ProviderCredential:
    access_token: str = field(repr=False)
    refresh_token: str | None = field(default=None, repr=False)
    client_id: str | None = field(default=None, repr=False)
    client_secret: str | None = field(default=None, repr=False)
    expires_at: str | None = field(default=None, repr=False)
    issued_at: str | None = field(default=None, repr=False)


def safe_raw(raw):
    # Only explicitly permitted business fields survive the provider boundary.
    allowed = {'id', 'username', 'display_name', 'media_type', 'media_kind', 'like_count', 'comments_count', 'followers_count'}
    value = {k: v for k, v in raw.items() if k in allowed}
    safe_metadata(value)
    return value


def checked_identifier(value, maximum=255):
    try:
        if not isinstance(value, str) or not value or len(value) > maximum:
            raise ValueError()
        safe_metadata(value)
    except ValueError:
        raise ProviderError('PROVIDER_RESPONSE_INVALID') from None


@dataclass(frozen=True)
class ProviderMetricDTO:
    values: dict[str, int | None] = field(default_factory=dict)
    observed_at: datetime | None = None

    def __post_init__(self):
        allowed = {'impressions', 'reach', 'views', 'likes', 'comments', 'shares', 'saves', 'followers', 'following', 'post_count'}
        if set(self.values) - allowed or any(v is not None and (type(v) is not int or v < 0) for v in self.values.values()):
            raise ProviderError('PROVIDER_RESPONSE_INVALID')
        if self.observed_at is not None and self.observed_at.utcoffset() is None:
            raise ProviderError('PROVIDER_RESPONSE_INVALID')


@dataclass(frozen=True)
class ProviderAccountDTO:
    remote_account_id: str
    username: str
    display_name: str | None = None
    profile_url: str | None = None
    observed_at: datetime | None = None
    metrics: ProviderMetricDTO = field(default_factory=ProviderMetricDTO)
    safe_raw: dict = field(default_factory=dict)

    def __post_init__(self):
        checked_identifier(self.remote_account_id)
        checked_identifier(self.username, 100)
        if self.observed_at is not None and self.observed_at.utcoffset() is None:
            raise ProviderError('PROVIDER_RESPONSE_INVALID')
        object.__setattr__(self, 'safe_raw', safe_raw(self.safe_raw))


@dataclass(frozen=True)
class ProviderPostDTO:
    remote_post_id: str
    remote_account_id: str
    posted_at: datetime
    text: str | None = None
    media_kind: str = 'TEXT'
    permalink: str | None = None
    metrics: ProviderMetricDTO = field(default_factory=ProviderMetricDTO)
    hashtags: list[str] = field(default_factory=list)
    safe_raw: dict = field(default_factory=dict)

    def __post_init__(self):
        checked_identifier(self.remote_post_id)
        checked_identifier(self.remote_account_id)
        if self.posted_at.utcoffset() is None:
            raise ProviderError('PROVIDER_RESPONSE_INVALID')
        object.__setattr__(self, 'safe_raw', safe_raw(self.safe_raw))


T = TypeVar('T')


@dataclass(frozen=True)
class ProviderPage(Generic[T]):
    records: list[T]
    next_cursor: str | None = None
    last_remote_id: str | None = None

    def __post_init__(self):
        try:
            safe_metadata([self.next_cursor, self.last_remote_id])
        except ValueError:
            raise ProviderError('PROVIDER_RESPONSE_INVALID') from None


@dataclass(frozen=True)
class ProviderValidationResult:
    remote_account_id: str
    capabilities: set[ProviderCapability]

    def __post_init__(self):
        checked_identifier(self.remote_account_id)
        checked_capabilities(self.capabilities)


@dataclass(frozen=True)
class ProviderContext:
    project_id: UUID
    provider_connection_id: UUID
    credential: ProviderCredential = field(repr=False)
    observation_time: datetime
    cursors: dict[str, str | None] = field(default_factory=dict)
    heartbeat: object = field(default=lambda: None, repr=False, compare=False)
    last_remote_ids: dict[str, str | None] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderFetchResult:
    account: ProviderAccountDTO
    posts: ProviderPage[ProviderPostDTO]


@dataclass(frozen=True)
class NormalizedAccountProfile:
    platform: str
    remote_account_id: str
    username: str
    display_name: str | None
    profile_url: str | None


class ExternalDataProvider(Protocol):
    provider_type: str
    def capabilities(self) -> set[ProviderCapability]: ...
    def validate_connection(self, credential: ProviderCredential) -> ProviderValidationResult: ...
    def fetch_account(self, context: ProviderContext) -> ProviderAccountDTO: ...
    def fetch_posts(self, context: ProviderContext, account: ProviderAccountDTO) -> ProviderPage[ProviderPostDTO]: ...


class ProviderNormalizer(Protocol):
    def normalize_account(self, account: ProviderAccountDTO, observed_at: datetime) -> tuple[NormalizedAccountProfile, NormalizedAccountMetric]: ...
    def normalize_posts(self, posts: list[ProviderPostDTO], account: ProviderAccountDTO) -> list[NormalizedPost]: ...


class ProviderRegistry:
    def __init__(self, factories=None):
        if factories is None:
            from app.providers.x_api_provider import XApiProvider, XProviderNormalizer
            from app.providers.instagram_api_provider import InstagramApiProvider, InstagramProviderNormalizer
            factories = {'X_API': lambda: (XApiProvider(), XProviderNormalizer()),
                         'INSTAGRAM_API': lambda: (InstagramApiProvider(), InstagramProviderNormalizer())}
        self.factories = dict(factories)

    def get(self, provider_type):
        factory = self.factories.get(provider_type)
        if factory is None:
            raise ProviderError('PROVIDER_NOT_IMPLEMENTED')
        provider, normalizer = factory()
        if provider.provider_type != provider_type:
            raise ProviderError('PROVIDER_SCOPE_INVALID')
        checked_capabilities(provider.capabilities())
        return provider, normalizer
