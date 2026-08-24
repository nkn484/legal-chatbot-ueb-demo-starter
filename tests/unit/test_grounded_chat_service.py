"""Focused fail-closed orchestration coverage for M06 Lane B."""

import logging
from uuid import UUID, uuid4

import pytest

from legal_chatbot.chat import (
    ChatOutcome,
    ChatReasonCode,
    ChatRequest,
    ChatSettings,
    ConversationContext,
    ConversationContextTurn,
    GroundedChatService,
    GroundingEvidence,
    GroundingExcerpt,
    ProviderAnswer,
    QueryPlannerOutcome,
    QueryPlannerPlan,
    QueryPlannerResult,
)
from legal_chatbot.chat.errors import ProviderOutputFailureClass
from legal_chatbot.chat.parser import StrictProviderJsonParser
from legal_chatbot.chat.prompt import build_grounded_prompt
from legal_chatbot.chat.service import validate_chat_provider_compatibility
from legal_chatbot.providers.config import ProviderSettings
from legal_chatbot.providers.errors import ProviderError
from legal_chatbot.providers.models import (
    GenerationRequest,
    GenerationResult,
    ProviderErrorCode,
    ProviderHealth,
    ProviderHealthStatus,
)
from legal_chatbot.retrieval.errors import RetrievalError, RetrievalErrorCode
from legal_chatbot.retrieval.models import (
    ResolvedCitation,
    RetrievalCandidate,
    RetrievalDecision,
    RetrievalReason,
    RetrievalRequest,
    RetrievalResult,
    TemporalScope,
)


def _provider_settings(**overrides: object) -> ProviderSettings:
    values: dict[str, object] = {
        "LLM_BASE_URL": "https://api.example.test/v1",
        "LLM_MODEL": "demo-model",
        "LLM_API_KEY": "test-key",
    }
    values.update(overrides)
    return ProviderSettings.model_validate(values)


def _citation(
    run_id: UUID, citation_id: UUID | None = None, chunk_id: UUID | None = None
) -> ResolvedCitation:
    return ResolvedCitation(
        citation_id=citation_id or uuid4(),
        retrieval_run_id=run_id,
        document_chunk_id=chunk_id or uuid4(),
        document_version_id=uuid4(),
        document_id=uuid4(),
        source_provenance_record_id=uuid4(),
        source_id="VBQPPL",
        external_id="external-id",
        title="grounding title",
    )


def _result(
    decision: RetrievalDecision = RetrievalDecision.EVIDENCE_AVAILABLE,
    *,
    count: int = 1,
) -> tuple[RetrievalResult, GroundingEvidence]:
    run_id = uuid4()
    citations = tuple(_citation(run_id) for _ in range(count))
    candidates = tuple(
        RetrievalCandidate(
            citation_id=citation.citation_id,
            document_chunk_id=citation.document_chunk_id,
            rank=index,
            lexical_score=1 / index,
        )
        for index, citation in enumerate(citations, start=1)
    )
    reason = {
        RetrievalDecision.EVIDENCE_AVAILABLE: RetrievalReason.LEXICAL_EVIDENCE_AVAILABLE,
        RetrievalDecision.NO_RESULTS: RetrievalReason.NO_LEXICAL_MATCH,
        RetrievalDecision.UNSUPPORTED_TEMPORAL_SCOPE: RetrievalReason.TEMPORAL_SCOPE_UNSUPPORTED,
        RetrievalDecision.INVALID_EVIDENCE_CHAIN: RetrievalReason.INVALID_EVIDENCE_CHAIN,
    }[decision]
    result = RetrievalResult(
        retrieval_run_id=run_id,
        candidates=candidates if decision is RetrievalDecision.EVIDENCE_AVAILABLE else (),
        candidate_count=count if decision is RetrievalDecision.EVIDENCE_AVAILABLE else 0,
        citation_count=count if decision is RetrievalDecision.EVIDENCE_AVAILABLE else 0,
        decision=decision,
        reason=reason,
    )
    evidence = GroundingEvidence(
        retrieval_run_id=run_id,
        excerpts=tuple(
            GroundingExcerpt(citation=citation, text="evidence text") for citation in citations
        ),
    )
    return result, evidence


class FakeRetrieval:
    def __init__(self, result: RetrievalResult | Exception) -> None:
        self.result = result
        self.calls: list[RetrievalRequest] = []

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        self.calls.append(request)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeGrounding:
    def __init__(self, result: GroundingEvidence | Exception) -> None:
        self.result = result
        self.calls: list[object] = []

    async def load(self, request: object) -> GroundingEvidence:
        self.calls.append(request)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeProvider:
    def __init__(
        self, result: GenerationResult | Exception, events: list[str] | None = None
    ) -> None:
        self.result = result
        self.calls: list[GenerationRequest] = []
        self.events = events

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.calls.append(request)
        if self.events is not None:
            self.events.append("provider")
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            status=ProviderHealthStatus.HEALTHY,
            provider="fake-provider",
            model="fake-model",
            duration_ms=0,
        )

    async def aclose(self) -> None:
        return None


class NonGenerationResultProvider(FakeProvider):
    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.calls.append(request)
        return object()  # type: ignore[return-value]


class FakeResolver:
    def __init__(
        self, citations: dict[UUID, ResolvedCitation] | Exception, events: list[str] | None = None
    ) -> None:
        self.citations = citations
        self.calls: list[tuple[UUID, UUID]] = []
        self.events = events

    async def resolve(self, citation_id: UUID, expected_retrieval_run_id: UUID) -> ResolvedCitation:
        self.calls.append((citation_id, expected_retrieval_run_id))
        if self.events is not None:
            self.events.append(f"resolver:{citation_id}")
        if isinstance(self.citations, Exception):
            raise self.citations
        return self.citations[citation_id]


def _generation(text: str = '{"answer":"model prose"}') -> GenerationResult:
    return GenerationResult(
        text=text,
        provider="fake-provider",
        model="fake-model",
        request_id="request-1",
        duration_ms=1,
    )


def _service(
    retrieval: FakeRetrieval,
    grounding: FakeGrounding,
    provider: FakeProvider,
    resolver: FakeResolver,
    *,
    parser: object | None = None,
    settings: ChatSettings | None = None,
    provider_settings: ProviderSettings | None = None,
    query_planner: object | None = None,
) -> GroundedChatService:
    return GroundedChatService(
        retrieval,
        grounding,
        resolver,
        provider,
        parser or StrictProviderJsonParser(),  # type: ignore[arg-type]
        settings or ChatSettings(),
        provider_settings or _provider_settings(),
        query_planner,  # type: ignore[arg-type]
    )


class FakeQueryPlanner:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def plan(self, question: str) -> QueryPlannerResult:
        self.calls.append(question)
        return QueryPlannerResult(outcome=QueryPlannerOutcome.SKIPPED_INPUT)


@pytest.mark.asyncio
async def test_no_results_returns_fixed_clarification_without_grounding_or_provider() -> None:
    result, evidence = _result(RetrievalDecision.NO_RESULTS)
    retrieval = FakeRetrieval(result)
    grounding = FakeGrounding(evidence)
    provider = FakeProvider(_generation())

    response = await _service(retrieval, grounding, provider, FakeResolver({})).respond(
        ChatRequest(question="no result question")
    )

    assert response.outcome is ChatOutcome.CLARIFICATION
    assert response.reason is ChatReasonCode.NO_RESULTS
    assert response.retrieval_run_id == result.retrieval_run_id
    assert grounding.calls == []
    assert provider.calls == []


@pytest.mark.asyncio
async def test_retrieval_query_is_retrieval_only_and_temporal_guard_uses_current_question() -> None:
    result, evidence = _result()
    retrieval = FakeRetrieval(result)
    provider = FakeProvider(_generation())
    resolver = FakeResolver(
        {excerpt.citation.citation_id: excerpt.citation for excerpt in evidence.excerpts}
    )
    response = await _service(retrieval, FakeGrounding(evidence), provider, resolver).respond(
        ChatRequest(question="current question", retrieval_query="as of retrieval query")
    )

    assert response.outcome is ChatOutcome.ANSWER
    assert retrieval.calls[0].query == "as of retrieval query"
    assert retrieval.calls[0].temporal_scope is TemporalScope.NONE
    assert "current question" in provider.calls[0].input_text
    assert "as of retrieval query" not in provider.calls[0].input_text


@pytest.mark.asyncio
async def test_context_temporal_phrases_do_not_change_retrieval_temporal_scope() -> None:
    result, evidence = _result()
    retrieval = FakeRetrieval(result)
    provider = FakeProvider(_generation())
    resolver = FakeResolver(
        {excerpt.citation.citation_id: excerpt.citation for excerpt in evidence.excerpts}
    )
    context = ConversationContext(
        rolling_summary="as of historical context",
        recent_turns=(
            ConversationContextTurn(role="USER", text="currently effective context", ordinal=1),
        ),
    )

    response = await _service(retrieval, FakeGrounding(evidence), provider, resolver).respond(
        ChatRequest(question="current question", conversation_context=context)
    )

    assert response.outcome is ChatOutcome.ANSWER
    assert retrieval.calls[0].temporal_scope is TemporalScope.NONE
    assert "UNTRUSTED_CONVERSATION_CONTEXT" in provider.calls[0].input_text


@pytest.mark.parametrize(
    "chat_request",
    [
        ChatRequest(question="explicit temporal", temporal_scope=TemporalScope.AS_OF),
        ChatRequest(question="What is currently effective?"),
    ],
)
@pytest.mark.asyncio
async def test_temporal_guards_return_fixed_refusal_without_provider(
    chat_request: ChatRequest,
) -> None:
    result, evidence = _result(RetrievalDecision.UNSUPPORTED_TEMPORAL_SCOPE)
    retrieval = FakeRetrieval(result)
    grounding = FakeGrounding(evidence)
    provider = FakeProvider(_generation())

    response = await _service(retrieval, grounding, provider, FakeResolver({})).respond(
        chat_request
    )

    assert response.reason is ChatReasonCode.UNSUPPORTED_TEMPORAL_SCOPE
    assert retrieval.calls[0].temporal_scope is not TemporalScope.NONE
    assert grounding.calls == []
    assert provider.calls == []


@pytest.mark.asyncio
async def test_disabled_and_temporal_requests_do_not_call_query_planner() -> None:
    result, evidence = _result()
    planner = FakeQueryPlanner()
    provider = FakeProvider(_generation())
    resolver = FakeResolver(
        {excerpt.citation.citation_id: excerpt.citation for excerpt in evidence.excerpts}
    )

    response = await _service(
        FakeRetrieval(result),
        FakeGrounding(evidence),
        provider,
        resolver,
        query_planner=planner,
    ).respond(ChatRequest(question="disabled planner"))
    assert response.outcome is ChatOutcome.ANSWER
    assert planner.calls == []

    temporal_result, temporal_evidence = _result(RetrievalDecision.UNSUPPORTED_TEMPORAL_SCOPE)
    response = await _service(
        FakeRetrieval(temporal_result),
        FakeGrounding(temporal_evidence),
        provider,
        FakeResolver({}),
        settings=ChatSettings(retrieval_planner_enabled=True),
        query_planner=planner,
    ).respond(ChatRequest(question="currently effective law"))
    assert response.reason is ChatReasonCode.UNSUPPORTED_TEMPORAL_SCOPE
    assert planner.calls == []


def test_expansion_query_uses_server_owned_or_between_quoted_validated_items() -> None:
    result, evidence = _result()
    service = _service(
        FakeRetrieval(result),
        FakeGrounding(evidence),
        FakeProvider(_generation()),
        FakeResolver({}),
    )

    query = service._build_expansion_query(
        QueryPlannerPlan(
            key_phrases=("tiêu chuẩn nghiên cứu",),
            expansion_terms=("hoạt động khoa học", "nhiệm vụ nghiên cứu"),
        ),
        "Tiêu chuẩn nghiên cứu là gì?",
    )

    assert query == '"tiêu chuẩn nghiên cứu" OR "hoạt động khoa học" OR "nhiệm vụ nghiên cứu"'


@pytest.mark.asyncio
async def test_invalid_chain_and_retrieval_failure_do_not_call_provider() -> None:
    invalid_chain, evidence = _result(RetrievalDecision.INVALID_EVIDENCE_CHAIN)
    provider = FakeProvider(_generation())
    response = await _service(
        FakeRetrieval(invalid_chain), FakeGrounding(evidence), provider, FakeResolver({})
    ).respond(ChatRequest(question="invalid chain"))
    assert response.reason is ChatReasonCode.INVALID_EVIDENCE_CHAIN
    assert provider.calls == []

    failed = FakeProvider(_generation())
    response = await _service(
        FakeRetrieval(RetrievalError(RetrievalErrorCode.PERSISTENCE_FAILURE)),
        FakeGrounding(evidence),
        failed,
        FakeResolver({}),
    ).respond(ChatRequest(question="retrieval failure"))
    assert response.reason is ChatReasonCode.RETRIEVAL_FAILURE
    assert response.retrieval_run_id is None
    assert failed.calls == []


@pytest.mark.asyncio
async def test_grounding_and_prompt_failures_do_not_call_provider() -> None:
    result, evidence = _result()
    provider = FakeProvider(_generation())
    response = await _service(
        FakeRetrieval(result),
        FakeGrounding(RuntimeError("untrusted evidence")),
        provider,
        FakeResolver({}),
    ).respond(ChatRequest(question="grounding error"))
    assert response.reason is ChatReasonCode.GROUNDING_FAILURE
    assert provider.calls == []

    small_settings = ChatSettings(
        question_max_chars=1,
        max_citations=1,
        excerpt_max_chars=1,
        total_evidence_max_chars=1,
        prompt_max_chars=2,
    )
    response = await _service(
        FakeRetrieval(result),
        FakeGrounding(evidence),
        provider,
        FakeResolver({}),
        settings=small_settings,
    ).respond(ChatRequest(question="q"))
    assert response.reason is ChatReasonCode.GROUNDING_FAILURE
    assert provider.calls == []


@pytest.mark.asyncio
async def test_eligible_path_calls_provider_once_and_reresolves_original_citations_in_order() -> (
    None
):
    result, evidence = _result(count=2)
    events: list[str] = []
    provider = FakeProvider(_generation(), events)
    resolver_citations = {
        excerpt.citation.citation_id: excerpt.citation.model_copy(
            update={"title": "resolver title"}
        )
        for excerpt in evidence.excerpts
    }
    resolver = FakeResolver(resolver_citations, events)

    class EventParser:
        def parse(self, output: str) -> ProviderAnswer:
            events.append("parser")
            return StrictProviderJsonParser().parse(output)

    response = await _service(
        FakeRetrieval(result), FakeGrounding(evidence), provider, resolver, parser=EventParser()
    ).respond(ChatRequest(question="eligible question"))

    assert response.outcome is ChatOutcome.ANSWER
    assert response.reason is ChatReasonCode.ANSWER_GROUNDED
    assert provider.calls == [
        GenerationRequest(
            input_text=build_grounded_prompt(
                ChatRequest(question="eligible question"), evidence, ChatSettings()
            ),
            max_output_tokens=ChatSettings().max_output_tokens,
        )
    ]
    assert [call[0] for call in resolver.calls] == [
        candidate.citation_id for candidate in result.candidates
    ]
    assert [call[1] for call in resolver.calls] == [result.retrieval_run_id] * 2
    assert events[:2] == ["provider", "parser"]
    assert all(event.startswith("resolver:") for event in events[2:])
    assert response.answer == "model prose"
    assert response.citations == tuple(resolver_citations[c.citation_id] for c in result.candidates)
    assert all(citation.title == "resolver title" for citation in response.citations)


@pytest.mark.asyncio
async def test_provider_and_output_failures_return_no_citations(
    caplog: pytest.LogCaptureFixture,
) -> None:
    result, evidence = _result()
    caplog.set_level(logging.INFO, logger="legal_chatbot")
    resolver = FakeResolver(
        {evidence.excerpts[0].citation.citation_id: evidence.excerpts[0].citation}
    )
    response = await _service(
        FakeRetrieval(result),
        FakeGrounding(evidence),
        FakeProvider(ProviderError(ProviderErrorCode.TIMEOUT)),
        resolver,
    ).respond(ChatRequest(question="provider failure"))
    assert response.reason is ChatReasonCode.PROVIDER_FAILURE
    assert response.citations == ()
    assert resolver.calls == []

    invalid_response = await _service(
        FakeRetrieval(result),
        FakeGrounding(evidence),
        FakeProvider(ProviderError(ProviderErrorCode.INVALID_RESPONSE)),
        FakeResolver({}),
    ).respond(ChatRequest(question="adapter invalid response"))
    assert invalid_response.reason is ChatReasonCode.PROVIDER_FAILURE
    assert "chat_provider_output_class" not in caplog.records[-1].__dict__

    malformed_provider = NonGenerationResultProvider(_generation())
    response = await _service(
        FakeRetrieval(result),
        FakeGrounding(evidence),
        malformed_provider,
        FakeResolver({}),
    ).respond(ChatRequest(question="malformed provider result"))
    assert response.outcome is ChatOutcome.REFUSAL
    assert response.reason is ChatReasonCode.INVALID_PROVIDER_OUTPUT
    assert len(malformed_provider.calls) == 1
    assert response.citations == ()

    oversized = _generation('{"answer":"' + "x" * 1_100 + '"}')
    response = await _service(
        FakeRetrieval(result),
        FakeGrounding(evidence),
        FakeProvider(oversized),
        FakeResolver({}),
        provider_settings=_provider_settings(LLM_MAX_RESPONSE_BYTES=1024),
    ).respond(ChatRequest(question="oversized"))
    assert response.reason is ChatReasonCode.INVALID_PROVIDER_OUTPUT
    assert response.citations == ()

    response = await _service(
        FakeRetrieval(result),
        FakeGrounding(evidence),
        FakeProvider(_generation("not json")),
        FakeResolver({}),
    ).respond(ChatRequest(question="bad parser"))
    assert response.reason is ChatReasonCode.INVALID_PROVIDER_OUTPUT
    assert response.citations == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("output", "failure_class"),
    [
        ("not json", ProviderOutputFailureClass.JSON_SYNTAX),
        ('{"answer":1}', ProviderOutputFailureClass.ANSWER_TYPE),
        ('{"answer":"https://example.test"}', ProviderOutputFailureClass.ANSWER_URL),
    ],
)
async def test_parser_output_classes_keep_generic_public_failure_and_skip_resolver(
    caplog: pytest.LogCaptureFixture,
    output: str,
    failure_class: ProviderOutputFailureClass,
) -> None:
    result, evidence = _result()
    resolver = FakeResolver(
        {evidence.excerpts[0].citation.citation_id: evidence.excerpts[0].citation}
    )
    caplog.set_level(logging.INFO, logger="legal_chatbot")

    response = await _service(
        FakeRetrieval(result), FakeGrounding(evidence), FakeProvider(_generation(output)), resolver
    ).respond(ChatRequest(question="output class"))

    assert response.reason is ChatReasonCode.INVALID_PROVIDER_OUTPUT
    assert response.citations == ()
    assert resolver.calls == []
    assert caplog.records[-1].__dict__["chat_provider_output_class"] == failure_class.value


@pytest.mark.asyncio
async def test_service_returns_safe_multiline_provider_answer_unchanged() -> None:
    result, evidence = _result()
    resolver = FakeResolver(
        {excerpt.citation.citation_id: excerpt.citation for excerpt in evidence.excerpts}
    )
    provider_answer = "First paragraph.\r\nSecond paragraph.\tDetail."
    response = await _service(
        FakeRetrieval(result),
        FakeGrounding(evidence),
        FakeProvider(_generation('{"answer":"First paragraph.\\r\\nSecond paragraph.\\tDetail."}')),
        resolver,
    ).respond(ChatRequest(question="multiline output"))

    assert response.outcome is ChatOutcome.ANSWER
    assert response.reason is ChatReasonCode.ANSWER_GROUNDED
    assert response.answer == provider_answer


@pytest.mark.asyncio
async def test_preparser_classes_are_logged_without_changing_public_result(
    caplog: pytest.LogCaptureFixture,
) -> None:
    result, evidence = _result()
    caplog.set_level(logging.INFO, logger="legal_chatbot")
    malformed_response = await _service(
        FakeRetrieval(result),
        FakeGrounding(evidence),
        NonGenerationResultProvider(_generation()),
        FakeResolver({}),
    ).respond(ChatRequest(question="malformed"))
    bytes_response = await _service(
        FakeRetrieval(result),
        FakeGrounding(evidence),
        FakeProvider(_generation('{"answer":"' + "x" * 1_100 + '"}')),
        FakeResolver({}),
        provider_settings=_provider_settings(LLM_MAX_RESPONSE_BYTES=1024),
    ).respond(ChatRequest(question="bytes"))

    assert malformed_response.reason is ChatReasonCode.INVALID_PROVIDER_OUTPUT
    assert bytes_response.reason is ChatReasonCode.INVALID_PROVIDER_OUTPUT
    assert [record.__dict__["chat_provider_output_class"] for record in caplog.records[-2:]] == [
        ProviderOutputFailureClass.PORT_RESULT_TYPE.value,
        ProviderOutputFailureClass.RESPONSE_BYTES.value,
    ]


@pytest.mark.asyncio
async def test_resolver_error_and_identity_mismatch_fail_closed_without_citations() -> None:
    result, evidence = _result()
    response = await _service(
        FakeRetrieval(result),
        FakeGrounding(evidence),
        FakeProvider(_generation()),
        FakeResolver(RetrievalError(RetrievalErrorCode.CITATION_NOT_FOUND)),
    ).respond(ChatRequest(question="resolver error"))
    assert response.reason is ChatReasonCode.CITATION_REVALIDATION_FAILURE
    assert response.citations == ()

    changed = evidence.excerpts[0].citation.model_copy(update={"document_id": uuid4()})
    response = await _service(
        FakeRetrieval(result),
        FakeGrounding(evidence),
        FakeProvider(_generation()),
        FakeResolver({changed.citation_id: changed}),
    ).respond(ChatRequest(question="identity mismatch"))
    assert response.reason is ChatReasonCode.CITATION_REVALIDATION_FAILURE
    assert response.citations == ()


def test_constructor_rejects_incompatible_provider_bounds() -> None:
    with pytest.raises(ValueError, match="incompatible"):
        validate_chat_provider_compatibility(
            ChatSettings(), _provider_settings(LLM_MAX_INPUT_CHARS=11_999)
        )


@pytest.mark.asyncio
async def test_service_logs_only_static_events_and_safe_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    result, evidence = _result()
    unsafe_evidence = evidence.model_copy(
        update={
            "excerpts": (evidence.excerpts[0].model_copy(update={"text": "EVIDENCE_SENTINEL"}),)
        }
    )
    caplog.set_level(logging.INFO, logger="legal_chatbot")
    response = await _service(
        FakeRetrieval(result),
        FakeGrounding(unsafe_evidence),
        FakeProvider(_generation('{"answer":"PROVIDER_OUTPUT_SENTINEL https://bad"}')),
        FakeResolver({}),
    ).respond(ChatRequest(question="QUESTION_SENTINEL"))

    assert response.reason is ChatReasonCode.INVALID_PROVIDER_OUTPUT
    assert caplog.records[-1].message == "grounded_chat_failed"
    serialized = str(caplog.records[-1].__dict__)
    assert all(
        sentinel not in serialized
        for sentinel in ("QUESTION_SENTINEL", "EVIDENCE_SENTINEL", "PROVIDER_OUTPUT_SENTINEL")
    )
    assert caplog.records[-1].__dict__["chat_provider_output_class"] == "ANSWER_URL"
