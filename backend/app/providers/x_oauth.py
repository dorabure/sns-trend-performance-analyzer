"""PKCE bootstrap and row-locked token rotation. Secrets remain in SecretStore."""
import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit
from uuid import UUID
from sqlalchemy import select, text
from app.db.models import ProviderConnection, Project
from app.providers.core import ProviderCredential, ProviderError
from app.providers.secret_store import ProviderCredentialResolver
from app.providers.http_client import ProviderHTTPClient
from app.providers.x_api_provider import flag, x_live_enabled, integer_setting, utc_datetime
from app.core.live_operations import live_enabled

SCOPES = ('tweet.read', 'users.read', 'offline.access')
CALLBACK_PATH = '/api/v1/providers/X_API/oauth/callback'


def oauth_enabled():
    return live_enabled() and flag('X_OAUTH_BOOTSTRAP_ENABLED')


def reference(provider):
    # Preserve Phase 5 bootstrap/runtime precedence; private projects should set
    # distinct logical references when authorizing different accounts.
    return provider.credential_ref or 'X_PRIMARY'


def lock_reference(session, name):
    # Different connections can intentionally share a logical credential. A
    # transaction-scoped PostgreSQL lock also serializes those token rotations.
    key = int.from_bytes(hashlib.sha256(('X_TOKEN_' + name).encode()).digest()[:8], 'big', signed=True)
    session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': key})


def token_payload(raw, now, *, old_refresh=None, require_scopes=True):
    try:
        if not isinstance(raw, dict) or raw.get('token_type', '').lower() != 'bearer':
            raise ValueError()
        access, refresh = raw.get('access_token'), raw.get('refresh_token', old_refresh)
        if any(not isinstance(v, str) or not v or len(v) > 8192 for v in (access, refresh)):
            raise ValueError()
        expires = raw.get('expires_in')
        if type(expires) is not int or not 0 < expires <= 31536000:
            raise ValueError()
        if require_scopes or 'scope' in raw:
            if not isinstance(raw.get('scope'), str) or not set(SCOPES) <= set(raw['scope'].split()):
                raise ProviderError('OAUTH_SCOPE_INSUFFICIENT')
        return {'schema_version': 1, 'access_token': access, 'refresh_token': refresh,
            'expires_at': (now + timedelta(seconds=expires)).isoformat()}
    except ProviderError:
        raise
    except Exception:
        raise ProviderError('PROVIDER_RESPONSE_INVALID') from None


class XTokenClient:
    def __init__(self, source, client=None):
        self.source, self.client = source, client or ProviderHTTPClient()

    def client_auth(self):
        client_id = self.source.get_secret('X_CLIENT_ID')
        client_type = os.getenv('X_OAUTH_CLIENT_TYPE', '').strip().upper()
        if not client_id or client_type not in ('PUBLIC', 'CONFIDENTIAL'):
            raise ProviderError('PROVIDER_NOT_CONFIGURED')
        authorization = None
        fields = {}
        if client_type == 'PUBLIC':
            fields['client_id'] = client_id
        else:
            client_secret = self.source.get_secret('X_CLIENT_SECRET')
            if not client_secret:
                raise ProviderError('PROVIDER_NOT_CONFIGURED')
            # RFC 6749 section 2.3.1: encode credentials before Basic encoding.
            from urllib.parse import quote_plus
            basic = quote_plus(client_id) + ':' + quote_plus(client_secret)
            authorization = 'Basic ' + base64.b64encode(basic.encode()).decode()
        return fields, authorization

    def exchange(self, form):
        fields, authorization = self.client_auth()
        form = dict(form) | fields
        return self.client.post_form(form, authorization=authorization)


class XCredentialManager:
    def __init__(self, factory, resolver=None, token_client=None, *, enabled=None, now=None):
        self.factory, self.resolver = factory, resolver or ProviderCredentialResolver()
        self.token_client = token_client or XTokenClient(self.resolver.source)
        self.enabled, self.now = enabled or x_live_enabled, now or (lambda: datetime.now(timezone.utc))

    def resolve_connection(self, provider, session=None):
        if provider.provider_type != 'X_API':
            return self.resolver.resolve(provider.provider_type, provider.credential_ref)
        if not self.enabled():
            raise ProviderError('X_LIVE_SMOKE_DISABLED')
        if session is not None:
            return self.locked(provider, session)
        with self.factory() as own, own.begin():
            return self.locked(provider, own)

    def locked(self, provider, session):
        row = session.scalar(select(ProviderConnection).where(ProviderConnection.id == provider.id).with_for_update().execution_options(populate_existing=True))
        if row is None or row.project_id != provider.project_id or row.provider_type != 'X_API':
            raise ProviderError('PROVIDER_SCOPE_INVALID')
        lock_reference(session, reference(row))
        # Live reads must remain refreshable. Reject incomplete bootstrap setup
        # before spending any API credit, even when the access token is valid.
        self.resolver.runtime.cipher()
        self.token_client.client_auth()
        credential = self.resolver.resolve('X_API', reference(row))
        if not credential.expires_at or not credential.refresh_token:
            # Bootstrap credentials without expiry require explicit provisioning.
            raise ProviderError('PROVIDER_NOT_CONFIGURED')
        expires = utc_datetime(credential.expires_at)
        skew = integer_setting('X_TOKEN_REFRESH_SKEW_SECONDS', 300, 0, 3600)
        if expires > self.now() + timedelta(seconds=skew):
            return credential
        if not flag('X_LIVE_REFRESH_SMOKE_ENABLED'):
            raise ProviderError('X_LIVE_REFRESH_DISABLED')
        raw = self.token_client.exchange({'grant_type': 'refresh_token', 'refresh_token': credential.refresh_token})
        payload = token_payload(raw, self.now(), old_refresh=credential.refresh_token, require_scopes=False)
        self.resolver.runtime.set_secret(reference(row), json.dumps(payload))
        return self.resolver.resolve('X_API', reference(row))


class XOAuthService:
    TTL = 600

    def __init__(self, factory, resolver=None, token_client=None, *, enabled=None, now=None):
        self.factory, self.resolver = factory, resolver or ProviderCredentialResolver()
        self.store = self.resolver.runtime
        self.tokens = token_client or XTokenClient(self.resolver.source)
        self.enabled, self.now = enabled or oauth_enabled, now or (lambda: datetime.now(timezone.utc))

    def guard(self):
        if not self.enabled():
            raise ProviderError('OAUTH_DISABLED')

    @staticmethod
    def pending_name(state):
        if not isinstance(state, str) or not 32 <= len(state) <= 128 or not all(c.isascii() and (c.isalnum() or c in '-_') for c in state):
            raise ProviderError('OAUTH_STATE_INVALID')
        return 'X_OAUTH_PENDING_' + hashlib.sha256(state.encode()).hexdigest().upper()

    @staticmethod
    def redirect():
        uri = os.getenv('X_OAUTH_REDIRECT_URI', '')
        parts = urlsplit(uri)
        # This phase supports private local callbacks only, with exact path.
        if parts.scheme != 'http' or parts.hostname not in ('127.0.0.1', 'localhost') or parts.username or parts.password or parts.path != CALLBACK_PATH or parts.query or parts.fragment:
            raise ProviderError('PROVIDER_NOT_CONFIGURED')
        return uri

    @staticmethod
    def connection(session, project_id, provider_id=None):
        project = session.get(Project, project_id)
        if not project or not project.is_active or project.data_mode != 'LIVE':
            raise ProviderError('OAUTH_PROVIDER_INVALID')
        query = select(ProviderConnection).where(ProviderConnection.project_id == project_id, ProviderConnection.provider_type == 'X_API')
        if provider_id is not None:
            query = query.where(ProviderConnection.id == provider_id)
        row = session.scalar(query.with_for_update())
        if not row:
            raise ProviderError('OAUTH_PROVIDER_INVALID')
        return row

    def start(self, project_id):
        self.guard()
        redirect = self.redirect()
        client_id = self.resolver.source.get_secret('X_CLIENT_ID')
        client_type = os.getenv('X_OAUTH_CLIENT_TYPE', '').strip().upper()
        if not client_id or client_type not in ('PUBLIC', 'CONFIDENTIAL') or client_type == 'CONFIDENTIAL' and not self.resolver.source.get_secret('X_CLIENT_SECRET'):
            raise ProviderError('PROVIDER_NOT_CONFIGURED')
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        with self.factory() as session, session.begin():
            row = self.connection(session, project_id)
            pending = {'project_id': str(project_id), 'provider_connection_id': str(row.id), 'state': state,
                'code_verifier': verifier, 'redirect_uri': redirect, 'created_at': self.now().isoformat(),
                'expires_at': (self.now() + timedelta(seconds=self.TTL)).isoformat()}
            self.store.set_secret(self.pending_name(state), json.dumps(pending))
        query = urlencode({'response_type': 'code', 'client_id': client_id, 'redirect_uri': redirect,
            'scope': ' '.join(SCOPES), 'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256'})
        return {'authorize_url': 'https://x.com/i/oauth2/authorize?' + query, 'expires_in': self.TTL}

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
            # Re-read under row lock: simultaneous callbacks exchange a code once.
            pending = self.pending(name, state)
            self.store.delete_secret(name)
            if error or not isinstance(code, str) or not code or len(code) > 8192:
                raise ProviderError('OAUTH_STATE_INVALID')
            raw = self.tokens.exchange({'grant_type': 'authorization_code', 'code': code,
                'redirect_uri': pending['redirect_uri'], 'code_verifier': pending['code_verifier']})
            payload = token_payload(raw, self.now())
            lock_reference(session, reference(row))
            self.store.set_secret(reference(row), json.dumps(payload))
        # No implicit enable, connect, validate or scheduled sync.
        return {'provider_type': 'X_API', 'authorized': True}

    def pending(self, name, state):
        try:
            raw = self.store.get_secret(name)
            pending = json.loads(raw) if raw else None
            if not isinstance(pending, dict) or not hmac.compare_digest(pending['state'], state) or pending['redirect_uri'] != self.redirect():
                raise ProviderError('OAUTH_STATE_INVALID')
            if utc_datetime(pending['expires_at']) <= self.now():
                self.store.delete_secret(name)
                raise ProviderError('OAUTH_STATE_EXPIRED')
            if not isinstance(pending['code_verifier'], str) or not 43 <= len(pending['code_verifier']) <= 128:
                raise ProviderError('OAUTH_STATE_INVALID')
            return pending
        except ProviderError:
            raise
        except Exception:
            raise ProviderError('OAUTH_STATE_INVALID') from None
