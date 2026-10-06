"""Lazy key loading, authenticated ciphertext and atomic per-secret replacement."""
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Protocol

from cryptography.fernet import Fernet
from app.core.provider_metadata import credential_reference
from app.providers.core import ProviderCredential, ProviderError


class SecretStore(Protocol):
    def get_secret(self, name: str) -> str | None: ...
    def set_secret(self, name: str, value: str) -> None: ...
    def delete_secret(self, name: str) -> None: ...


class EnvOrFileSecretSource:
    def __init__(self, environ=None):
        self.environ = os.environ if environ is None else environ

    def get_secret(self, name):
        try:
            file = self.environ.get(name + '_FILE')
            if file:
                return Path(file).read_text(encoding='utf-8').strip() or None
            return self.environ.get(name, '').strip() or None
        except Exception:
            raise ProviderError('SECRET_STORE_UNAVAILABLE') from None


class EncryptedFileSecretStore:
    def __init__(self, directory=None, source=None):
        self.directory = Path(directory or os.getenv('RUNTIME_SECRET_STORE_DIR', '/var/lib/sns-analyzer/secrets'))
        self.source = source or EnvOrFileSecretSource()

    def cipher(self):
        try:
            # Reject a configured key file co-located with the ciphertext directory.
            key_file = self.source.environ.get('RUNTIME_SECRET_KEY_FILE')
            if key_file and Path(key_file).resolve().is_relative_to(self.directory.resolve()):
                raise ValueError()
            key = self.source.get_secret('RUNTIME_SECRET_KEY')
            if not key:
                raise ValueError()
            return Fernet(key.encode())
        except Exception:
            raise ProviderError('SECRET_STORE_UNAVAILABLE') from None

    def path(self, name):
        try:
            if not isinstance(name, str) or not name:
                raise ValueError()
            credential_reference(name)
        except ValueError:
            raise ProviderError('SECRET_STORE_UNAVAILABLE')
        return self.directory / (hashlib.sha256(name.encode('utf-8')).hexdigest() + '.enc')

    def get_secret(self, name):
        try:
            cipher = self.cipher()  # Missing/wrong key never silently falls back.
            path = self.path(name)
            if not path.exists():
                return None
            if path.is_symlink() or path.stat().st_size > 65536:
                raise ValueError()
            payload = json.loads(cipher.decrypt(path.read_bytes()))
            if payload['schema_version'] != 1 or not isinstance(payload['value'], str):
                raise ValueError()
            return payload['value']
        except Exception:
            raise ProviderError('SECRET_STORE_UNAVAILABLE') from None

    def set_secret(self, name, value):
        temporary = None
        try:
            if not isinstance(value, str) or len(value.encode()) > 32768:
                raise ValueError()
            encrypted = self.cipher().encrypt(json.dumps({'schema_version': 1, 'value': value}).encode())
            path = self.path(name)
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.directory.chmod(0o700)
            fd, temporary = tempfile.mkstemp(dir=self.directory, prefix='.replace-')
            with os.fdopen(fd, 'wb') as stream:
                os.chmod(temporary, 0o600)
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            temporary = None
            self.sync_directory()
        except Exception:
            raise ProviderError('SECRET_STORE_UNAVAILABLE') from None
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)

    def sync_directory(self):
        if os.name == 'posix':
            fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    def delete_secret(self, name):
        try:
            self.cipher()
            self.path(name).unlink(missing_ok=True)
            if self.directory.exists():
                self.sync_directory()
        except Exception:
            raise ProviderError('SECRET_STORE_UNAVAILABLE') from None


class ProviderCredentialResolver:
    def __init__(self, source=None, runtime=None):
        self.source = source or EnvOrFileSecretSource()
        self.runtime = runtime or EncryptedFileSecretStore(source=self.source)

    def resolve(self, provider_type, reference=None):
        prefix = {'X_API': 'X', 'INSTAGRAM_API': 'INSTAGRAM'}.get(provider_type)
        if prefix is None:
            raise ProviderError('PROVIDER_NOT_IMPLEMENTED')
        ref = reference or prefix + '_PRIMARY'
        try:
            credential_reference(ref)
            # Without a runtime key, bootstrap-only credentials remain usable. If
            # ciphertext exists, a missing key is an unavailable store, not fallback.
            key = self.source.get_secret('RUNTIME_SECRET_KEY')
            has_runtime = self.runtime.path(ref).exists()
            raw = self.runtime.get_secret(ref) if key or has_runtime else None
            overlay = json.loads(raw) if raw else {}
            allowed = {'schema_version', 'access_token', 'refresh_token', 'expires_at'}
            if provider_type == 'INSTAGRAM_API':
                allowed.add('issued_at')
            if not isinstance(overlay, dict) or set(overlay) - allowed:
                raise ValueError()
            if overlay and overlay.get('schema_version') != 1:
                raise ValueError()
            def value(field, env):
                result = overlay.get(field) or self.source.get_secret(prefix + '_' + env)
                if result is not None and not isinstance(result, str):
                    raise ValueError()
                return result
            access = value('access_token', 'USER_ACCESS_TOKEN')
            if not access:
                raise ProviderError('PROVIDER_NOT_CONFIGURED')
            return ProviderCredential(access, value('refresh_token', 'REFRESH_TOKEN'),
                self.source.get_secret(prefix + '_CLIENT_ID'), self.source.get_secret(prefix + '_CLIENT_SECRET'),
                value('expires_at', 'TOKEN_EXPIRES_AT'),
                value('issued_at', 'TOKEN_ISSUED_AT') if provider_type == 'INSTAGRAM_API' else None)
        except ProviderError:
            raise
        except Exception:
            raise ProviderError('SECRET_STORE_UNAVAILABLE') from None

    def configured(self, provider_type, reference=None):
        try:
            self.resolve(provider_type, reference)
            return True
        except ProviderError:
            return False
