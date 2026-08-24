"""Runtime composition checks for opt-in semantic hybrid retrieval."""

from __future__ import annotations

from typing import cast

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from legal_chatbot.channels.config import ChannelSettings
from legal_chatbot.chat.config import ChatSettings
from legal_chatbot.providers.config import ProviderSettings
from legal_chatbot.retrieval.config import RetrievalSettings
from legal_chatbot.runtime import m08


class _Closable:
    async def aclose(self) -> None:
        return None


def _channel_settings() -> ChannelSettings:
    return ChannelSettings(
        enabled=True,
        bot_token=SecretStr("token-value-012345"),
        webhook_secret=SecretStr("webhook-secret-012345"),
        identity_hmac_key=SecretStr("identity-key-012345678901234567890123"),
    )


def _provider_settings() -> ProviderSettings:
    return ProviderSettings.model_validate(
        {"LLM_BASE_URL": "https://api.example.test/v1", "LLM_MODEL": "demo", "LLM_API_KEY": "key"}
    )


def _factories() -> dict[str, object]:
    return {
        "provider_factory": lambda _settings: _Closable(),
        "session_factory_factory": lambda _engine: object(),
        "lexical_repository_factory": lambda *_args: object(),
        "retrieval_service_factory": lambda _repository: object(),
        "grounding_evidence_factory": lambda *_args: object(),
        "citation_resolver_factory": lambda _session_factory: object(),
        "parser_factory": lambda: object(),
        "grounded_chat_service_factory": lambda *_args: object(),
        "conversation_repository_factory": lambda *_args: object(),
        "conversation_service_factory": lambda *_args: object(),
        "binding_repository_factory": lambda *_args: object(),
        "outbound_repository_factory": lambda *_args: object(),
        "formatter_factory": lambda _settings: object(),
        "channel_factory": lambda *_args: _Closable(),
        "channel_service_factory": lambda *_args: object(),
    }


@pytest.fixture(autouse=True)
def _active_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(m08, "_active_source_ids_from_registry", lambda: ("VBQPPL",))


@pytest.mark.asyncio
async def test_hybrid_runtime_disabled_never_constructs_semantic_embedder() -> None:
    factories = _factories()
    runtime = await m08.build_m08_runtime(
        cast(AsyncEngine, object()),
        _channel_settings(),
        provider_settings=_provider_settings(),
        semantic_embedder_factory=lambda _settings: (_ for _ in ()).throw(AssertionError),
        **factories,  # type: ignore[arg-type]
    )
    assert runtime is not None
    await runtime.aclose()


@pytest.mark.asyncio
async def test_hybrid_runtime_incomplete_coverage_fails_before_adapter_construction() -> None:
    factories = _factories()
    with pytest.raises(RuntimeError, match="M08_RUNTIME_CONSTRUCTION_FAILED"):
        await m08.build_m08_runtime(
            cast(AsyncEngine, object()),
            _channel_settings(),
            provider_settings=_provider_settings(),
            retrieval_settings=RetrievalSettings(semantic_hybrid_enabled=True),
            semantic_coverage_checker=lambda *_args: _false(),
            semantic_embedder_factory=lambda _settings: (_ for _ in ()).throw(AssertionError),
            **factories,  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_hybrid_runtime_rejects_planner_and_repair_attribution_mix() -> None:
    with pytest.raises(RuntimeError, match="M08_SEMANTIC_HYBRID_INCOMPATIBLE_OPTIONS"):
        await m08.build_m08_runtime(
            cast(AsyncEngine, object()),
            _channel_settings(),
            provider_settings=_provider_settings(),
            chat_settings=ChatSettings(retrieval_planner_enabled=True),
            retrieval_settings=RetrievalSettings(semantic_hybrid_enabled=True),
            **_factories(),  # type: ignore[arg-type]
        )


async def _false() -> bool:
    return False
