"""Explicitly gated live M06 grounded-chat smoke against persisted VBQPPL evidence."""

from __future__ import annotations

import json
import os
import re
from typing import Final

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from legal_chatbot.chat import ChatOutcome, ChatReasonCode, ChatRequest, ChatSettings
from legal_chatbot.chat.parser import StrictProviderJsonParser
from legal_chatbot.chat.service import GroundedChatService
from legal_chatbot.core.config import Settings
from legal_chatbot.db.session import create_engine, create_session_factory
from legal_chatbot.documents.citation_resolver import PostgresCitationResolver
from legal_chatbot.documents.grounding_evidence import PostgresGroundingEvidenceAdapter
from legal_chatbot.documents.retrieval_repository import PostgresLexicalRetrievalRepository
from legal_chatbot.providers.config import ProviderSettings
from legal_chatbot.providers.models import (
    GenerationRequest,
    GenerationResult,
    ProviderHealth,
    ProviderHealthStatus,
    sanitize_request_id,
)
from legal_chatbot.providers.port import LLMProviderPort
from legal_chatbot.providers.registry import create_provider
from legal_chatbot.retrieval.service import RetrievalService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION") != "1" or os.getenv("RUN_M06_SHINE_LIVE") != "1",
        reason="set RUN_INTEGRATION=1 and RUN_M06_SHINE_LIVE=1 for live M06 SHINE",
    ),
]

_TRACEABILITY_FIELDS: Final = (
    "citation_id",
    "retrieval_run_id",
    "document_chunk_id",
    "document_version_id",
    "document_id",
    "source_provenance_record_id",
)
_UUID_REQUEST_ID_PATTERN: Final = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
_HASH_REQUEST_ID_PATTERN: Final = re.compile(r"^[0-9a-f]{32,}$", re.IGNORECASE)


def _safe_output_request_id(value: str | None) -> str | None:
    """Keep only sanitized request IDs that cannot be UUID or hash-shaped values."""

    request_id = sanitize_request_id(value)
    if request_id is None:
        return None
    if _UUID_REQUEST_ID_PATTERN.fullmatch(request_id) or _HASH_REQUEST_ID_PATTERN.fullmatch(
        request_id
    ):
        return None
    return request_id


class CountingProvider:
    """Delegate to the registry-created provider while recording generation calls only."""

    def __init__(self, delegate: LLMProviderPort) -> None:
        self._delegate = delegate
        self.generation_calls = 0

    async def health_check(self) -> ProviderHealth:
        return await self._delegate.health_check()

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.generation_calls += 1
        return await self._delegate.generate(request)

    async def aclose(self) -> None:
        await self._delegate.aclose()


@pytest.mark.asyncio
async def test_m06_grounded_chat_shine_live_vbqppl_smoke() -> None:
    """Require one real grounded answer, preserving the retrieval evidence it creates."""

    query = os.getenv("M06_LIVE_QUERY", "").strip()
    if not query:
        pytest.skip("set M06_LIVE_QUERY to run live M06 SHINE")

    settings = Settings()
    provider_settings = ProviderSettings()
    chat_settings = ChatSettings()
    engine: AsyncEngine | None = None
    provider: CountingProvider | None = None

    try:
        engine = create_engine(settings)

        provider = CountingProvider(create_provider(provider_settings))
        health = await provider.health_check()
        assert health.status is ProviderHealthStatus.HEALTHY
        assert health.provider == provider_settings.provider
        assert health.model == provider_settings.model

        session_factory = create_session_factory(engine)
        service = GroundedChatService(
            RetrievalService(PostgresLexicalRetrievalRepository(session_factory, ("VBQPPL",))),
            PostgresGroundingEvidenceAdapter(session_factory, chat_settings),
            PostgresCitationResolver(session_factory),
            provider,
            StrictProviderJsonParser(),
            chat_settings,
            provider_settings,
        )
        result = await service.respond(ChatRequest(question=query))

        traceability_complete = result.retrieval_run_id is not None and all(
            all(getattr(citation, field) is not None for field in _TRACEABILITY_FIELDS)
            for citation in result.citations
        )
        assert result.outcome is ChatOutcome.ANSWER
        assert result.reason is ChatReasonCode.ANSWER_GROUNDED
        assert result.citations
        assert all(citation.source_id == "VBQPPL" for citation in result.citations)
        assert traceability_complete
        assert provider.generation_calls == 1
        assert result.provider == provider_settings.provider
        assert result.model == provider_settings.model

        print(
            json.dumps(
                {
                    "probe": "m06_grounded_chat_shine_live",
                    "outcome": "PASS",
                    "chat_outcome": result.outcome.value,
                    "chat_reason": result.reason.value,
                    "provider": result.provider,
                    "model": result.model,
                    "health_status": health.status.value,
                    "health_request_id": _safe_output_request_id(health.request_id),
                    "generation_request_id": _safe_output_request_id(result.provider_request_id),
                    "generation_calls": provider.generation_calls,
                    "citation_count": len(result.citations),
                    "traceability_complete": traceability_complete,
                    "semantic_used": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    finally:
        if provider is not None:
            await provider.aclose()
        if engine is not None:
            await engine.dispose()
