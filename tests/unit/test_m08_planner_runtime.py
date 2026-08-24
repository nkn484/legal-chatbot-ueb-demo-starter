"""Composition coverage for the M08.1 planner runtime seam."""

from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from legal_chatbot.channels.config import ChannelSettings
from legal_chatbot.chat.config import ChatSettings
from legal_chatbot.chat.planner_models import QueryPlannerOutcome, QueryPlannerResult
from legal_chatbot.documents.canonical_anchor_resolver import PostgresCanonicalAnchorResolver
from legal_chatbot.providers.config import ProviderSettings
from legal_chatbot.runtime import m08 as m08_runtime
from legal_chatbot.runtime.m08 import build_m08_runtime


@pytest.fixture(autouse=True)
def _disable_local_demo_corpus(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep composition tests independent from the operator's enabled demo `.env`."""

    monkeypatch.setenv("DEMO_CORPUS_ENABLED", "false")


def _channel_settings() -> ChannelSettings:
    return ChannelSettings(
        enabled=True,
        bot_token=SecretStr("token-value-012345"),
        webhook_secret=SecretStr("webhook-secret-012345"),
        identity_hmac_key=SecretStr("identity-key-012345678901234567890123"),
    )


def _provider_settings() -> ProviderSettings:
    return ProviderSettings.model_validate(
        {
            "LLM_BASE_URL": "https://api.example.test/v1",
            "LLM_MODEL": "demo-model",
            "LLM_API_KEY": "test-key",
        }
    )


class _Closable:
    async def aclose(self) -> None:
        return None


class _Planner:
    async def plan(self, question: str) -> QueryPlannerResult:
        return QueryPlannerResult(outcome=QueryPlannerOutcome.SKIPPED_INPUT)


class _CanonicalResolver:
    async def resolve(self, anchor_mentions: tuple[str, ...]) -> tuple[UUID, ...] | None:
        return None


def _runtime_factories(
    captured: list[tuple[object, ...]],
    provider: _Closable,
    session_factory: object,
) -> dict[str, object]:
    def grounded_chat_factory(*args: object) -> object:
        captured.append(args)
        return object()

    return {
        "provider_factory": lambda _settings: provider,
        "session_factory_factory": lambda _engine: session_factory,
        "lexical_repository_factory": lambda _session_factory, _active_source_ids: object(),
        "retrieval_service_factory": lambda _repository: object(),
        "grounding_evidence_factory": lambda _session_factory, _settings: object(),
        "citation_resolver_factory": lambda _session_factory: object(),
        "parser_factory": lambda: object(),
        "grounded_chat_service_factory": grounded_chat_factory,
        "conversation_repository_factory": lambda _session_factory, _settings: object(),
        "conversation_service_factory": lambda *_args: object(),
        "binding_repository_factory": lambda _session_factory, _settings: object(),
        "outbound_repository_factory": lambda _session_factory, _settings: object(),
        "formatter_factory": lambda _settings: object(),
        "channel_factory": lambda _settings, _recipients: _Closable(),
        "channel_service_factory": lambda *_args: object(),
    }


@pytest.mark.asyncio
async def test_disabled_planner_constructs_neither_planner_nor_canonical_resolver() -> None:
    captured: list[tuple[object, ...]] = []
    factories = _runtime_factories(captured, _Closable(), object())

    runtime = await build_m08_runtime(
        cast(AsyncEngine, object()),
        _channel_settings(),
        provider_settings=_provider_settings(),
        chat_settings=ChatSettings(),
        query_planner_factory=lambda *_args: (_ for _ in ()).throw(AssertionError),
        canonical_anchor_resolver_factory=(
            lambda _session_factory, _active_source_ids: (_ for _ in ()).throw(AssertionError)
        ),
        **factories,  # type: ignore[arg-type]
    )

    assert runtime is not None
    assert captured[0][-2:] == (None, None)
    await runtime.aclose()


@pytest.mark.asyncio
async def test_enabled_planner_constructs_both_components_with_owned_provider_and_session() -> None:
    captured: list[tuple[object, ...]] = []
    provider = _Closable()
    session_factory = object()
    planner = _Planner()
    canonical_resolver = _CanonicalResolver()
    factories = _runtime_factories(captured, provider, session_factory)
    planner_calls: list[tuple[object, object, object]] = []
    resolver_calls: list[object] = []

    runtime = await build_m08_runtime(
        cast(AsyncEngine, object()),
        _channel_settings(),
        provider_settings=_provider_settings(),
        chat_settings=ChatSettings(retrieval_planner_enabled=True),
        query_planner_factory=lambda current_provider, settings, provider_settings: (
            planner_calls.append((current_provider, settings, provider_settings)) or planner
        ),
        canonical_anchor_resolver_factory=lambda current_session_factory, active_source_ids: (
            resolver_calls.append((current_session_factory, active_source_ids))
            or canonical_resolver
        ),
        **factories,  # type: ignore[arg-type]
    )

    assert runtime is not None
    assert len(planner_calls) == 1
    assert planner_calls[0][0] is provider
    assert planner_calls[0][1] == ChatSettings(retrieval_planner_enabled=True)
    assert planner_calls[0][2] == _provider_settings()
    assert resolver_calls == [(session_factory, ("VBQPPL",))]
    assert captured[0][-2:] == (planner, canonical_resolver)
    await runtime.aclose()


def test_active_source_set_derives_only_active_sources_from_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = cast(async_sessionmaker[AsyncSession], object())
    registry_path = Path("registry.json")
    registry = SimpleNamespace(
        systems=(
            SimpleNamespace(id="VBQPPL", lifecycle="ACTIVE"),
            SimpleNamespace(id="VNU", lifecycle="PLANNED"),
            SimpleNamespace(id="UEB", lifecycle="PLANNED"),
        )
    )
    loaded_paths: list[Path] = []
    monkeypatch.setattr(
        m08_runtime, "SourceSettings", lambda: SimpleNamespace(registry_path=registry_path)
    )
    monkeypatch.setattr(
        m08_runtime,
        "load_registry",
        lambda path: loaded_paths.append(path) or registry,
    )

    active_source_ids = m08_runtime._active_source_ids_from_registry()
    resolver = m08_runtime._registry_canonical_anchor_resolver_factory(
        session_factory, active_source_ids
    )

    assert isinstance(resolver, PostgresCanonicalAnchorResolver)
    assert resolver._active_source_ids == ("VBQPPL",)
    assert loaded_paths == [registry_path]


@pytest.mark.asyncio
async def test_runtime_passes_one_identical_registry_tuple_to_retrieval_and_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        m08_runtime, "SourceSettings", lambda: SimpleNamespace(registry_path=Path("registry.json"))
    )
    monkeypatch.setattr(
        m08_runtime,
        "load_registry",
        lambda _path: SimpleNamespace(
            systems=(
                SimpleNamespace(id="VBQPPL", lifecycle="ACTIVE"),
                SimpleNamespace(id="VNU", lifecycle="PLANNED"),
            )
        ),
    )
    captured: list[tuple[object, ...]] = []
    source_sets: list[tuple[str, ...]] = []
    factories = _runtime_factories(captured, _Closable(), object())
    factories["lexical_repository_factory"] = lambda _session_factory, source_ids: (
        source_sets.append(source_ids) or object()
    )
    factories["canonical_anchor_resolver_factory"] = lambda _session_factory, source_ids: (
        source_sets.append(source_ids) or _CanonicalResolver()
    )

    runtime = await build_m08_runtime(
        cast(AsyncEngine, object()),
        _channel_settings(),
        provider_settings=_provider_settings(),
        chat_settings=ChatSettings(retrieval_planner_enabled=True),
        query_planner_factory=lambda *_args: _Planner(),
        **factories,  # type: ignore[arg-type]
    )

    assert runtime is not None
    assert source_sets == [("VBQPPL",), ("VBQPPL",)]
    assert source_sets[0] is source_sets[1]
    await runtime.aclose()


@pytest.mark.asyncio
async def test_no_active_registry_fails_enabled_runtime_construction_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        m08_runtime, "SourceSettings", lambda: SimpleNamespace(registry_path=Path("registry.json"))
    )
    monkeypatch.setattr(
        m08_runtime,
        "load_registry",
        lambda _path: SimpleNamespace(
            systems=(
                SimpleNamespace(id="VBQPPL", lifecycle="PLANNED"),
                SimpleNamespace(id="VNU", lifecycle="PLANNED"),
                SimpleNamespace(id="UEB", lifecycle="PLANNED"),
            )
        ),
    )
    factories = _runtime_factories([], _Closable(), object())

    with pytest.raises(RuntimeError, match="M08_RUNTIME_CONSTRUCTION_FAILED"):
        await build_m08_runtime(
            cast(AsyncEngine, object()),
            _channel_settings(),
            provider_settings=_provider_settings(),
            chat_settings=ChatSettings(retrieval_planner_enabled=True),
            query_planner_factory=lambda *_args: _Planner(),
            **factories,  # type: ignore[arg-type]
        )
