"""Reject credentials in provider metadata; no credential storage in Phase 2."""
import re


_SECRET_KEYS = {
    "token", "accesstoken", "refreshtoken", "clientsecret", "authorization",
    "authorizationheader", "apikey", "openaiapikey", "password", "secret", "secretjson",
}
_SECRET_VALUE = re.compile(r"(?:\bBearer\s+|\bsk-(?:proj-)?|-----BEGIN .*PRIVATE KEY-----)", re.I)


def safe_metadata(value):
    """Validate nested JSON before ORM persistence; never echo rejected values."""
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized in _SECRET_KEYS or normalized.endswith(("accesstoken", "refreshtoken", "clientsecret", "apikey")):
                raise ValueError("Credentials are not allowed in provider metadata")
            safe_metadata(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            safe_metadata(child)
    elif isinstance(value, str) and _SECRET_VALUE.search(value):
        raise ValueError("Credentials are not allowed in provider metadata")
    return value


def credential_reference(value):
    if value is not None and (not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", value)):
        raise ValueError("Credential reference must be a logical identifier")
    return value
