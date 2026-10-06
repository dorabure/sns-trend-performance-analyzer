"""Fail-closed sync admission using current implementation and validated metadata."""
from app.providers.core import ProviderError, checked_capabilities


SYNC_CAPABILITIES = frozenset({'ACCOUNT_PROFILE', 'OWN_POSTS', 'OWN_METRICS'})


def sync_capabilities_available(provider, registry, *, require_stored=True):
    try:
        remote, _ = registry.get(provider.provider_type)
        current = set(checked_capabilities(remote.capabilities()))
        if not SYNC_CAPABILITIES <= current:
            return False
        return not require_stored or SYNC_CAPABILITIES <= set(checked_capabilities(provider.capabilities))
    except (ProviderError, ValueError, TypeError):
        return False
