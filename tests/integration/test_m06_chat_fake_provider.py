"""Fake-only M06 composition test with no API, live provider, or PostgreSQL dependency."""

from uuid import uuid4

import pytest

from legal_chatbot.chat import ChatOutcome, ChatRequest, ChatSettings, GroundedChatService
from legal_chatbot.chat.models import GroundingEvidence, GroundingExcerpt
from legal_chatbot.chat.parser import StrictProviderJsonParser
from legal_chatbot.providers.config import ProviderSettings
from legal_chatbot.providers.models import GenerationResult, ProviderHealth, ProviderHealthStatus
from legal_chatbot.retrieval.models import (
    ResolvedCitation,
    RetrievalCandidate,
    RetrievalDecision,
    RetrievalReason,
    RetrievalResult,
)


@pytest.mark.asyncio
async def test_fake_only_composition_returns_real_grounded_contracts() -> None:
    run_id = uuid4()
    citation = ResolvedCitation(
        citation_id=uuid4(),
        retrieval_run_id=run_id,
        document_chunk_id=uuid4(),
        document_version_id=uuid4(),
        document_id=uuid4(),
        source_provenance_record_id=uuid4(),
        source_id="VBQPPL",
        external_id="123",
    )

    class RetrievalFake:
        async def retrieve(self, request: object) -> RetrievalResult:
            return RetrievalResult(
                retrieval_run_id=run_id,
                candidates=(
                    RetrievalCandidate(
                        citation_id=citation.citation_id,
                        document_chunk_id=citation.document_chunk_id,
                        rank=1,
                        lexical_score=1,
                    ),
                ),
                candidate_count=1,
                citation_count=1,
                decision=RetrievalDecision.EVIDENCE_AVAILABLE,
                reason=RetrievalReason.LEXICAL_EVIDENCE_AVAILABLE,
            )

    class GroundingFake:
        async def load(self, request: object) -> GroundingEvidence:
            return GroundingEvidence(
                retrieval_run_id=run_id,
                excerpts=(GroundingExcerpt(citation=citation, text="Real evidence."),),
            )

    class ProviderFake:
        async def generate(self, request: object) -> GenerationResult:
            return GenerationResult(
                text='{"answer":"A real parser result."}',
                provider="fake",
                model="fake-model",
                duration_ms=0,
            )

        async def health_check(self) -> ProviderHealth:
            return ProviderHealth(
                status=ProviderHealthStatus.HEALTHY,
                provider="fake",
                model="fake-model",
                duration_ms=0,
            )

        async def aclose(self) -> None:
            return None

    class ResolverFake:
        async def resolve(
            self, citation_id: object, expected_retrieval_run_id: object
        ) -> ResolvedCitation:
            assert citation_id == citation.citation_id
            assert expected_retrieval_run_id == run_id
            return citation

    service = GroundedChatService(
        RetrievalFake(),
        GroundingFake(),
        ResolverFake(),
        ProviderFake(),
        StrictProviderJsonParser(),
        ChatSettings(),
        ProviderSettings.model_validate(
            {
                "LLM_BASE_URL": "https://api.example.test/v1",
                "LLM_MODEL": "fake-model",
                "LLM_API_KEY": "fake-key",
            }
        ),
    )

    result = await service.respond(ChatRequest(question="What does the evidence say?"))

    assert result.outcome is ChatOutcome.ANSWER
    assert result.answer == "A real parser result."
    assert result.citations == (citation,)
