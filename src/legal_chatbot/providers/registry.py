"""Provider factory registry with lazy adapter imports."""

from collections.abc import Callable

import httpx

from legal_chatbot.providers.config import ProviderSettings
from legal_chatbot.providers.errors import ProviderError
from legal_chatbot.providers.models import ProviderErrorCode
from legal_chatbot.providers.port import LLMProviderPort

type ProviderFactory = Callable[[ProviderSettings, httpx.AsyncClient | None], LLMProviderPort]


def _normalize_name(name: str) -> str:
    return name.strip().lower()


class ProviderRegistry:
    """Register and instantiate named provider factories without adapter imports."""

    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory] = {}

    def register(self, name: str, factory: ProviderFactory) -> None:
        normalized_name = _normalize_name(name)
        if not normalized_name or normalized_name in self._factories:
            raise ProviderError(ProviderErrorCode.REQUEST_REJECTED, status_code=400)
        self._factories[normalized_name] = factory

    def create(
        self,
        name: str,
        settings: ProviderSettings,
        client: httpx.AsyncClient | None = None,
    ) -> LLMProviderPort:
        factory = self._factories.get(_normalize_name(name))
        if factory is None:
            raise ProviderError(ProviderErrorCode.PROVIDER_NOT_CONFIGURED, status_code=503)
        return factory(settings, client)


def _create_shineshop(
    settings: ProviderSettings, client: httpx.AsyncClient | None
) -> LLMProviderPort:
    """Import the active adapter only after the default registry selects it."""
    from legal_chatbot.providers.adapters.shineshop import ShineShopAdapter

    return ShineShopAdapter(settings, client=client)


def create_default_registry() -> ProviderRegistry:
    """Build the runtime registry with the active SHINE SHOP factory."""
    registry = ProviderRegistry()
    registry.register("shineshop", _create_shineshop)
    return registry


def create_provider(
    settings: ProviderSettings,
    client: httpx.AsyncClient | None = None,
    registry: ProviderRegistry | None = None,
) -> LLMProviderPort:
    """Resolve the configured provider through a supplied or default registry."""
    resolved_registry = registry if registry is not None else create_default_registry()
    return resolved_registry.create(settings.provider, settings, client)
