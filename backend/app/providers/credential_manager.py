"""Provider-specific credential lifecycle routing; X behavior is unchanged."""
from typing import Protocol
from app.providers.core import ProviderCredential, ProviderError
from app.providers.x_oauth import XCredentialManager
from app.providers.instagram_oauth import InstagramCredentialManager


class CredentialManagerProtocol(Protocol):
    def resolve_connection(self, provider, session=None) -> ProviderCredential: ...


class CredentialManagerRouter:
    def __init__(self, factory, *, x_manager=None, instagram_manager=None):
        self.managers = {'X_API': x_manager or XCredentialManager(factory),
            'INSTAGRAM_API': instagram_manager or InstagramCredentialManager(factory)}

    def resolve_connection(self, provider, session=None):
        manager = self.managers.get(provider.provider_type)
        if manager is None:
            raise ProviderError('PROVIDER_NOT_IMPLEMENTED')
        return manager.resolve_connection(provider, session)
