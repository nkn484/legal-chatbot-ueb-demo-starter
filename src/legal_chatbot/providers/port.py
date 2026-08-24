"""Provider boundary that isolates Chat from provider SDKs and HTTP details."""

from typing import Protocol

from legal_chatbot.providers.models import GenerationRequest, GenerationResult, ProviderHealth


class LLMProviderPort(Protocol):
    """Async contract every LLM provider adapter must implement."""

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        """Generate text for a bounded request."""
        ...

    async def health_check(self) -> ProviderHealth:
        """Return normalized provider health without raising raw SDK errors."""
        ...

    async def aclose(self) -> None:
        """Release any adapter-owned async resources."""
        ...
