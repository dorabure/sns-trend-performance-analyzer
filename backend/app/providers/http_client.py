"""Sync interface with async HTTPX transport for a cancellable total deadline."""
import asyncio
import json
import math
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import httpx
from app.providers.core import ProviderError


@dataclass(frozen=True)
class ProviderHTTPResponse:
    data: object = field(repr=False)
    rate_limit_limit: int | None = None
    rate_limit_remaining: int | None = None
    rate_limit_reset: int | None = None


def rate_number(value):
    if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 18:
        return int(value)
    return None


class ProviderHTTPClient:
    def __init__(self, *, transport=None, sleep=time.sleep, jitter=None, request_timeout=30):
        self.sleep, self.jitter = sleep, jitter or random.random
        def setting(name, default, maximum):
            try:
                value = float(os.getenv(name, default))
                if not math.isfinite(value) or not 0 < value <= maximum:
                    raise ValueError()
                return value
            except (ValueError, TypeError):
                raise ProviderError('PROVIDER_BAD_REQUEST') from None
        connect = setting('PROVIDER_CONNECT_TIMEOUT_SECONDS', '5', 5)
        read = setting('PROVIDER_READ_TIMEOUT_SECONDS', '20', 20)
        self.retry_cap = setting('PROVIDER_MAX_RETRY_AFTER_SECONDS', '60', 60)
        if not math.isfinite(request_timeout) or not 0 < request_timeout <= 30:
            raise ProviderError('PROVIDER_BAD_REQUEST')
        self.request_timeout = request_timeout
        self.timeout = httpx.Timeout(connect=connect, read=read, write=5, pool=5)
        self.transport = transport

    @staticmethod
    def retry_after(value):
        if value is None:
            return None
        try:
            delay = float(value)
        except (ValueError, TypeError):
            try:
                delay = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
            except Exception:
                return None
        return max(0, delay) if math.isfinite(delay) else None

    async def attempt(self, transport, url, credential, params, *, form=None, authorization=None, multipart=False):
        request = httpx.Request('POST' if form is not None else 'GET', url, params=params,
            data=None if multipart else form,
            files={key: (None, value) for key, value in form.items()} if multipart else None,
            headers={'Authorization': authorization or ('Bearer ' + credential.access_token)} if authorization or credential else {},
            extensions={'timeout': self.timeout.as_dict()})
        response = await transport.handle_async_request(request)
        try:
            status = response.status_code
            codes = {400: 'PROVIDER_BAD_REQUEST', 401: 'PROVIDER_AUTH_FAILED', 403: 'PROVIDER_PERMISSION_DENIED', 429: 'PROVIDER_RATE_LIMITED'}
            if status >= 300:
                code = codes.get(status, 'PROVIDER_SERVER_ERROR' if status >= 500 else 'PROVIDER_BAD_REQUEST')
                reset = rate_number(response.headers.get('x-rate-limit-reset'))
                delay = max(0, reset - time.time()) if status == 429 and reset is not None else self.retry_after(response.headers.get('Retry-After'))
                if form is not None and status == 400:
                    # OAuth invalid_grant is an authentication failure. Never echo its body.
                    code = 'PROVIDER_AUTH_FAILED'
                raise ProviderError(code, retryable=status == 429 or status >= 500, retry_after_seconds=delay)
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > 4 * 1024 * 1024:
                    raise ProviderError('PROVIDER_RESPONSE_INVALID')
                chunks.append(chunk)
            try:
                result = json.loads(b''.join(chunks))
                if not isinstance(result, (dict, list)):
                    raise ValueError()
                return ProviderHTTPResponse(result, *(rate_number(response.headers.get('x-rate-limit-' + name)) for name in ('limit', 'remaining', 'reset')))
            except Exception:
                raise ProviderError('PROVIDER_RESPONSE_INVALID') from None
        finally:
            await response.aclose()

    async def execute(self, url, credential, params, heartbeat, *, form=None, authorization=None, single_attempt=False, multipart=False):
        # Loop-local pool: no async connections are shared across sync invocations.
        # Direct transport avoids HTTPX Client INFO request logs containing URLs.
        transport = self.transport or httpx.AsyncHTTPTransport(verify=True, retries=0)
        try:
            # Authorization codes and rotating refresh tokens are single-use.
            # Do not replay token POSTs after an ambiguous transport failure.
            attempts = 1 if form is not None or single_attempt else 3
            for attempt in range(attempts):
                heartbeat()
                try:
                    return await asyncio.wait_for(self.attempt(transport, url, credential, params, form=form, authorization=authorization, multipart=multipart), self.request_timeout)
                except (TimeoutError, httpx.TimeoutException):
                    error = ProviderError('PROVIDER_TIMEOUT', retryable=True)
                except httpx.TransportError:
                    error = ProviderError('PROVIDER_NETWORK_ERROR', retryable=True)
                except ProviderError as failure:
                    error = failure
                except Exception:
                    error = ProviderError('PROVIDER_RESPONSE_INVALID')
                finally:
                    heartbeat()
                if error.retry_after_seconds is not None and error.retry_after_seconds > self.retry_cap:
                    raise ProviderError('PROVIDER_RATE_LIMITED', retry_after_seconds=self.retry_cap) from None
                if not error.retryable or attempt == attempts - 1:
                    raise error from None
                delay = error.retry_after_seconds if error.retry_after_seconds is not None else min(2 ** attempt + self.jitter(), self.retry_cap)
                self.sleep(delay)
        finally:
            await transport.aclose()

    def get_json(self, url, credential, *, params=None, heartbeat=lambda: None):
        return self.get_response(url, credential, params=params, heartbeat=heartbeat).data

    def get_response(self, url, credential, *, params=None, heartbeat=lambda: None):
        try:
            parsed = httpx.URL(url)
            if parsed.scheme != 'https' or parsed.userinfo or parsed.query or not parsed.host:
                raise ValueError()
            from app.core.provider_metadata import safe_metadata
            safe_metadata(params or {})
        except Exception:
            raise ProviderError('PROVIDER_BAD_REQUEST') from None
        return asyncio.run(self.execute(parsed, credential, params, heartbeat))

    def post_form(self, form, *, authorization=None, heartbeat=lambda: None):
        allowed = {'grant_type', 'code', 'redirect_uri', 'code_verifier', 'refresh_token', 'client_id'}
        if not isinstance(form, dict) or set(form) - allowed or any(not isinstance(v, str) or not v or len(v) > 8192 for v in form.values()):
            raise ProviderError('PROVIDER_BAD_REQUEST')
        if form.get('grant_type') not in ('authorization_code', 'refresh_token'):
            raise ProviderError('PROVIDER_BAD_REQUEST')
        return asyncio.run(self.execute(httpx.URL('https://api.x.com/2/oauth2/token'), None, None, heartbeat,
            form=form, authorization=authorization)).data

    def instagram_token(self, operation, fields, *, heartbeat=lambda: None):
        # Fixed endpoints only. These GETs change token lifecycle and must not be
        # retried after an ambiguous failure. Never pass secret query fields to
        # the generic GET API, HTTPX Client logs, or a caller-supplied URL.
        contracts = {
            'code': ('https://api.instagram.com/oauth/access_token', 'authorization_code',
                     {'grant_type', 'client_id', 'client_secret', 'code', 'redirect_uri'}),
            'exchange': ('https://graph.instagram.com/access_token', 'ig_exchange_token',
                         {'grant_type', 'client_secret', 'access_token'}),
            'refresh': ('https://graph.instagram.com/refresh_access_token', 'ig_refresh_token',
                        {'grant_type', 'access_token'}),
        }
        contract = contracts.get(operation)
        if contract is None or not isinstance(fields, dict):
            raise ProviderError('PROVIDER_BAD_REQUEST')
        url, grant, allowed = contract
        if set(fields) != allowed or fields.get('grant_type') != grant or any(
                not isinstance(v, str) or not v or len(v) > 8192 for v in fields.values()):
            raise ProviderError('PROVIDER_BAD_REQUEST')
        return asyncio.run(self.execute(httpx.URL(url), None,
            None if operation == 'code' else fields, heartbeat,
            form=fields if operation == 'code' else None, single_attempt=True, multipart=operation == 'code')).data
