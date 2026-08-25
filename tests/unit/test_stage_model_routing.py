import json
from uuid import uuid4

import pytest

from legal_chatbot.legal_evidence import (
    AnalysisOrigin,
    AuthorityState,
    CandidateDocument,
    CaseStage,
    DocumentVersionReference,
    QuestionAnalysis,
    SubIntent,
    advance_case,
    create_legal_case,
)
from legal_chatbot.legal_evidence.analyzer import (
    LegalQuestionAnalyzerSettings,
    LLMLegalQuestionAnalyzer,
)
from legal_chatbot.legal_evidence.authority import (
    AuthorityMetadata,
    AuthorityReviewOutcome,
    AuthorityReviewService,
    AuthorityReviewSettings,
)
from legal_chatbot.legal_evidence.routing import (
    LegalStageModelRoutingSettings,
    StageProviderCircuitBreaker,
)
from legal_chatbot.providers.models import GenerationResult


class _P2Provider:
    def __init__(self, result: str | Exception) -> None:
        self.result = result
        self.calls = 0

    async def generate(self, request):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return GenerationResult(text=self.result, provider="stub", model="stub", duration_ms=1)


def test_stage_settings_are_independent_and_p2_defaults_to_deterministic_first() -> None:
    settings = LegalStageModelRoutingSettings(
        LEGAL_P2_MODEL="fast-structured",
        LEGAL_P4_MODEL="reasoning-capable",
        LEGAL_P2_TIMEOUT_SECONDS=2,
        LEGAL_P4_TIMEOUT_SECONDS=12,
    )

    assert settings.p2_deterministic_first is True
    assert settings.p2_model == "fast-structured"
    assert settings.p4_model == "reasoning-capable"
    assert settings.p2_timeout_seconds != settings.p4_timeout_seconds


@pytest.mark.asyncio
async def test_p2_deterministic_first_skips_optional_provider() -> None:
    provider = _P2Provider(RuntimeError("must not be called"))
    analyzer = LLMLegalQuestionAnalyzer(
        provider, settings=LegalQuestionAnalyzerSettings(enabled=True)
    )

    result = await analyzer.analyze(create_legal_case("Thẩm quyền và quy trình là gì?"))

    assert provider.calls == 0
    assert result.analysis.origin is AnalysisOrigin.DETERMINISTIC_FALLBACK


@pytest.mark.asyncio
async def test_p2_failure_opens_stage_circuit_and_next_request_is_suppressed() -> None:
    provider = _P2Provider(TimeoutError())
    circuit = StageProviderCircuitBreaker(suppression_seconds=60)
    analyzer = LLMLegalQuestionAnalyzer(
        provider,
        settings=LegalQuestionAnalyzerSettings(enabled=True, deterministic_first=False),
        circuit_breaker=circuit,
    )
    context = create_legal_case("Thẩm quyền và quy trình là gì?")

    first = await analyzer.analyze(context)
    second = await analyzer.analyze(context)

    assert first.outcome.value == "FALLBACK_PROVIDER_TIMEOUT"
    assert second.outcome.value == "FALLBACK_PROVIDER_SUPPRESSED"
    assert provider.calls == 1


def _document() -> DocumentVersionReference:
    return DocumentVersionReference(
        document_id=uuid4(),
        document_version_id=uuid4(),
        provenance_record_id=uuid4(),
        source_id="UEB",
    )


def _authority_context(documents: tuple[DocumentVersionReference, ...]):
    sub_intent = SubIntent(
        code="AUTHORITY", description="authority", retrieval_concepts=("thẩm quyền",)
    )
    analyzed = advance_case(
        create_legal_case("private routing test"),
        CaseStage.ANALYZED,
        question_analysis=QuestionAnalysis(
            origin=AnalysisOrigin.DETERMINISTIC_FALLBACK, main_intent="authority"
        ),
        sub_intents=(sub_intent,),
    )
    context = advance_case(
        analyzed,
        CaseStage.DISCOVERED,
        candidate_documents=tuple(
            CandidateDocument(
                document=document,
                state=AuthorityState.ELIGIBLE,
                matched_sub_intent_ids=(sub_intent.sub_intent_id,),
            )
            for document in documents
        ),
    )
    metadata = tuple(
        AuthorityMetadata(
            document=document,
            discovery_state=AuthorityState.ELIGIBLE,
            provenance_valid=True,
            scope_compatible=True,
            source_binding_compatible=True,
            status_eligible=True,
            title="Quy định về thẩm quyền",
            document_type="Quy chế",
        )
        for document in documents
    )
    return context, metadata


class _P4Provider:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, request):
        self.calls += 1
        if self.calls == 2:
            raise TimeoutError()
        return GenerationResult(
            text=json.dumps(
                {
                    "assessments": [
                        {"candidate_index": index, "sub_intent_index": 0, "role": "GOVERNING"}
                        for index in range(2)
                    ]
                }
            ),
            provider="stub",
            model="stub",
            duration_ms=1,
        )


@pytest.mark.asyncio
async def test_p4_partial_batch_failure_merges_success_and_fallback_without_duplicates() -> None:
    documents = tuple(_document() for _ in range(3))
    context, metadata = _authority_context(documents)
    provider = _P4Provider()
    result = await AuthorityReviewService(
        provider,
        AuthorityReviewSettings(enabled=True, batch_size=2, batch_max_attempts=1),
    ).review_case(context, metadata)

    assert result.outcome is AuthorityReviewOutcome.BATCH_PARTIAL_FAILURE
    assert result.result.llm_assessment_count == 2
    assert result.result.fallback_assessment_count == 1
    assert len(result.assessments) == 3
    assert len({item.document.document_version_id for item in result.assessments}) == 3


@pytest.mark.asyncio
async def test_p4_open_circuit_suppresses_provider_and_keeps_deterministic_assessments() -> None:
    document = _document()
    context, metadata = _authority_context((document,))
    provider = _P4Provider()
    circuit = StageProviderCircuitBreaker(suppression_seconds=60)
    circuit.record_failure("P4")
    result = await AuthorityReviewService(
        provider,
        AuthorityReviewSettings(enabled=True),
        circuit_breaker=circuit,
    ).review_case(context, metadata)

    assert result.outcome is AuthorityReviewOutcome.PROVIDER_SUPPRESSED
    assert provider.calls == 0
    assert len(result.assessments) == 1
