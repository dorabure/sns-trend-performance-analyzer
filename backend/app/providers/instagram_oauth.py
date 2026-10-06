"""Instagram Login OAuth and long-lived token refresh, fixed Meta endpoints."""
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit
from uuid import UUID
from sqlalchemy import select, text
from app.core.live_operations import live_enabled
from app.db.models import ProviderConnection, Project
from app.providers.core import ProviderError
from app.providers.http_client import ProviderHTTPClient
from app.providers.secret_store import ProviderCredentialResolver
from app.providers.instagram_api_provider import flag, instagram_live_enabled, identifier

SCOPES = ('instagram_business_basic', 'instagram_business_manage_insights')
CALLBACK_PATH = '/api/v1/providers/INSTAGRAM_API/oauth/callback'
MIN_REFRESH_AGE_SECONDS = 86400
MAX_TOKEN_LIFETIME_SECONDS = 60 * 86400


def utc_datetime(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.utcoffset() is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except Exception:
        raise ProviderError('PROVIDER_RESPONSE_INVALID') from None


def reference(provider):
    return provider.credential_ref or 'INSTAGRAM_PRIMARY'


def lock_reference(session, name):
    key = int.from_bytes(hashlib.sha256(('INSTAGRAM_TOKEN_' + name).encode()).digest()[:8], 'big', signed=True)
    session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': key})


def token_payload(raw, now):
    try:
        if not isinstance(raw, dict) or raw.get('token_type', '').lower() != 'bearer':
            raise ValueError()
        token, expires = raw.get('access_token'), raw.get('expires_in')
        if not isinstance(token, str) or not token or len(token) > 8192:
            raise ValueError()
        if type(expires) is not int or not 0 < expires <= MAX_TOKEN_LIFETIME_SECONDS:
            raise ValueError()
        return {'schema_version': 1, 'access_token': token,
            'expires_at': (now + timedelta(seconds=expires)).isoformat(), 'issued_at': now.isoformat()}
    except Exception:
        raise ProviderError('PROVIDER_RESPONSE_INVALID') from None


class InstagramTokenClient:
    def __init__(self, source, client=None):
        self.source, self.client = source, client or ProviderHTTPClient()

    def client_auth(self):
        client_id = self.source.get_secret('INSTAGRAM_CLIENT_ID')
        secret = self.source.get_secret('INSTAGRAM_CLIENT_SECRET')
        if not isinstance(client_id, str) or not client_id.isascii() or not client_id.isdigit() or not secret:
            raise ProviderError('PROVIDER_NOT_CONFIGURED')
        return client_id, secret

    def exchange_code(self, code, redirect):
        client_id, secret = self.client_auth()
        raw = self.client.instagram_token('code', {'grant_type': 'authorization_code',
            'client_id': client_id, 'client_secret': secret, 'code': code, 'redirect_uri': redirect})
        try:
            if not isinstance(raw, dict) or not isinstance(raw.get('data'), list) or len(raw['data']) != 1:
                raise ValueError()
            record = raw['data'][0]
            identifier(record['user_id'])
            permissions = record.get('permissions')
            if not isinstance(permissions, str) or not set(SCOPES) <= set(permissions.replace(',', ' ').split()):
                raise ProviderError('OAUTH_SCOPE_INSUFFICIENT')
            access = record['access_token']
            if not isinstance(access, str) or not access or len(access) > 8192:
                raise ValueError()
            return access
        except ProviderError:
            raise
        except Exception:
            raise ProviderError('PROVIDER_RESPONSE_INVALID') from None

    def long_lived(self, access):
        _, secret = self.client_auth()
        return self.client.instagram_token('exchange', {'grant_type': 'ig_exchange_token',
            'client_secret': secret, 'access_token': access})

    def refresh(self, access):
        return self.client.instagram_token('refresh', {'grant_type': 'ig_refresh_token', 'access_token': access})


class InstagramCredentialManager:
    def __init__(self, factory, resolver=None, token_client=None, *, enabled=None, now=None):
        self.factory, self.resolver = factory, resolver or ProviderCredentialResolver()
        self.tokens = token_client or InstagramTokenClient(self.resolver.source)
        self.enabled, self.now = enabled or instagram_live_enabled, now or (lambda: datetime.now(timezone.utc))

    def resolve_connection(self, provider, session=None):
        return self.resolve(provider, session)

    def refresh_connection(self, provider, session=None):
        # Explicit private verification can request refresh once Meta's actual
        # minimum age is met; it never alters timestamps or bypasses expiry.
        return self.resolve(provider, session, force_refresh=True)

    def resolve(self, provider, session=None, *, force_refresh=False):
        if provider.provider_type != 'INSTAGRAM_API':
            raise ProviderError('PROVIDER_SCOPE_INVALID')
        if not self.enabled():
            raise ProviderError('INSTAGRAM_LIVE_SMOKE_DISABLED')
        if session is not None:
            return self.locked(provider, session, force_refresh=force_refresh)
        with self.factory() as own, own.begin():
            return self.locked(provider, own, force_refresh=force_refresh)

    def locked(self, provider, session, *, force_refresh=False):
        row = session.scalar(select(ProviderConnection).where(ProviderConnection.id == provider.id)
            .with_for_update().execution_options(populate_existing=True))
        if row is None or row.project_id != provider.project_id or row.provider_type != 'INSTAGRAM_API':
            raise ProviderError('PROVIDER_SCOPE_INVALID')
        lock_reference(session, reference(row))
        self.resolver.runtime.cipher()
        credential = self.resolver.resolve('INSTAGRAM_API', reference(row))
        if not credential.expires_at or not credential.issued_at:
            raise ProviderError('PROVIDER_NOT_CONFIGURED')
        expires, issued, now = utc_datetime(credential.expires_at), utc_datetime(credential.issued_at), self.now()
        if issued > now or issued >= expires or expires - issued > timedelta(seconds=MAX_TOKEN_LIFETIME_SECONDS):
            raise ProviderError('PROVIDER_RESPONSE_INVALID')
        if expires <= now:
            raise ProviderError('INSTAGRAM_REAUTH_REQUIRED')
        try:
            skew = int(os.getenv('INSTAGRAM_TOKEN_REFRESH_SKEW_SECONDS', '604800'))
            if not 0 <= skew <= 30 * 86400:
                raise ValueError()
        except Exception:
            raise ProviderError('PROVIDER_BAD_REQUEST') from None
        if not force_refresh and expires > now + timedelta(seconds=skew):
            return credential
        if not flag('INSTAGRAM_LIVE_REFRESH_SMOKE_ENABLED'):
            raise ProviderError('INSTAGRAM_LIVE_REFRESH_DISABLED')
        if now - issued < timedelta(seconds=MIN_REFRESH_AGE_SECONDS):
            raise ProviderError('INSTAGRAM_REFRESH_TOO_EARLY')
        payload = token_payload(self.tokens.refresh(credential.access_token), self.now())
        self.resolver.runtime.set_secret(reference(row), json.dumps(payload))
        return self.resolver.resolve('INSTAGRAM_API', reference(row))


class InstagramOAuthService:
    TTL = 600

    def __init__(self, factory, resolver=None, token_client=None, *, enabled=None, now=None):
        self.factory, self.resolver = factory, resolver or ProviderCredentialResolver()
        self.store = self.resolver.runtime
        self.tokens = token_client or InstagramTokenClient(self.resolver.source)
        self.enabled = enabled or (lambda: live_enabled() and flag('INSTAGRAM_OAUTH_BOOTSTRAP_ENABLED'))
        self.now = now or (lambda: datetime.now(timezone.utc))

    def guard(self):
        if not self.enabled():
            raise ProviderError('OAUTH_DISABLED')

    @staticmethod
    def pending_name(state):
        if not isinstance(state, str) or not 32 <= len(state) <= 128 or not all(
                c.isascii() and (c.isalnum() or c in '-_') for c in state):
            raise ProviderError('OAUTH_STATE_INVALID')
        return 'INSTAGRAM_OAUTH_PENDING_' + hashlib.sha256(state.encode()).hexdigest().upper()

    @staticmethod
    def redirect():
        uri = os.getenv('INSTAGRAM_OAUTH_REDIRECT_URI', '')
        parts = urlsplit(uri)
        # Meta documents exact matching to the registered redirect. HTTPS only
        # until official loopback HTTP support is verified for this login flow.
        if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.path != CALLBACK_PATH or parts.query or parts.fragment:
            raise ProviderError('PROVIDER_NOT_CONFIGURED')
        return uri

    @staticmethod
    def connection(session, project_id, provider_id=None):
        project = session.get(Project, project_id)
        if not project or not project.is_active or project.data_mode != 'LIVE':
            raise ProviderError('OAUTH_PROVIDER_INVALID')
        query = select(ProviderConnection).where(ProviderConnection.project_id == project_id,
            ProviderConnection.provider_type == 'INSTAGRAM_API')
        if provider_id is not None:
            query = query.where(ProviderConnection.id == provider_id)
        row = session.scalar(query.with_for_update())
        if row is None:
            raise ProviderError('OAUTH_PROVIDER_INVALID')
        return row

    def start(self, project_id):
        self.guard()
        redirect = self.redirect()
        client_id, _ = self.tokens.client_auth()
        state, now = secrets.token_urlsafe(32), self.now()
        with self.factory() as session, session.begin():
            row = self.connection(session, project_id)
            pending = {'project_id': str(project_id), 'provider_connection_id': str(row.id),
                'state': state, 'redirect_uri': redirect, 'created_at': now.isoformat(),
                'expires_at': (now + timedelta(seconds=self.TTL)).isoformat()}
            self.store.set_secret(self.pending_name(state), json.dumps(pending))
        query = urlencode({'response_type': 'code', 'client_id': client_id, 'redirect_uri': redirect,
            'scope': ','.join(SCOPES), 'state': state, 'enable_fb_login': 'false'})
        # PKCE is not specified by Meta's Instagram Business Login contract.
        return {'authorize_url': 'https://www.instagram.com/oauth/authorize?' + query, 'expires_in': self.TTL}

    def pending(self, name, state):
        try:
            raw = self.store.get_secret(name)
            pending = json.loads(raw) if raw else None
            if not isinstance(pending, dict) or not hmac.compare_digest(pending['state'], state) or pending['redirect_uri'] != self.redirect():
                raise ProviderError('OAUTH_STATE_INVALID')
            created, expires, now = utc_datetime(pending['created_at']), utc_datetime(pending['expires_at']), self.now()
            if created > now or expires - created != timedelta(seconds=self.TTL):
                raise ProviderError('OAUTH_STATE_INVALID')
            if expires <= now:
                self.store.delete_secret(name)
                raise ProviderError('OAUTH_STATE_EXPIRED')
            return pending
        except ProviderError:
            raise
        except Exception:
            raise ProviderError('OAUTH_STATE_INVALID') from None

    def callback(self, *, state=None, code=None, error=None):
        self.guard()
        name = self.pending_name(state)
        pending = self.pending(name, state)
        try:
            project_id, provider_id = UUID(pending['project_id']), UUID(pending['provider_connection_id'])
        except Exception:
            raise ProviderError('OAUTH_PROVIDER_INVALID') from None
        with self.factory() as session, session.begin():
            row = self.connection(session, project_id, provider_id)
            pending = self.pending(name, state)
            self.store.delete_secret(name)
            if error or not isinstance(code, str) or not code or len(code) > 8192:
                raise ProviderError('OAUTH_STATE_INVALID')
            lock_reference(session, reference(row))
            short = self.tokens.exchange_code(code, pending['redirect_uri'])
            payload = token_payload(self.tokens.long_lived(short), self.now())
            self.store.set_secret(reference(row), json.dumps(payload))
        return {'provider_type': 'INSTAGRAM_API', 'authorized': True}
