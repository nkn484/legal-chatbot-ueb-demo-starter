# Provider Strategy

Demo provider is SHINE SHOP. Runtime settings are external: `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`.

Conceptual port:
```python
class LLMProviderPort(Protocol):
    async def generate(self, request: GenerationRequest) -> GenerationResult: ...
    async def health_check(self) -> ProviderHealth: ...
```

Future Claude uses a separate Anthropic adapter. Chat must not change when switching adapters. Demo resilience: timeout, bounded safe retry, request-id capture, normalized failures.
