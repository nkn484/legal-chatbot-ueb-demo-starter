"""Provider contracts and provider factory registry."""

from legal_chatbot.providers.config import ProviderSettings
from legal_chatbot.providers.errors import ProviderError
from legal_chatbot.providers.models import (
    GenerationRequest,
    GenerationResult,
    ProviderErrorCode,
    ProviderHealth,
    sanitize_request_id,
)
from legal_chatbot.providers.port import LLMProviderPort
from legal_chatbot.providers.registry import (
    ProviderRegistry,
    create_default_registry,
    create_provider,
)

__all__ = [
    "GenerationRequest",
    "GenerationResult",
    "LLMProviderPort",
    "ProviderHealth",
    "ProviderError",
    "ProviderErrorCode",
    "ProviderRegistry",
    "ProviderSettings",
    "create_default_registry",
    "create_provider",
    "sanitize_request_id",
]
