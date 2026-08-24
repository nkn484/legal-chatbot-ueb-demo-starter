"""Focused contract coverage for pure M06 Phase 1 chat models."""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from legal_chatbot.chat import (
    ANSWER_MAX_CHARS,
    CONVERSATION_CONTEXT_MAX_CHARS,
    CONVERSATION_CONTEXT_TURN_LIMIT,
    EXCERPT_MAX_CHARS,
    QUESTION_MAX_CHARS,
    TOTAL_EVIDENCE_MAX_CHARS,
    ChatOutcome,
    ChatPolicyDecision,
    ChatReasonCode,
    ChatRequest,
    ConversationContext,
    ConversationContextTurn,
    GroundedChatResult,
    GroundingEvidence,
    GroundingEvidenceRequest,
    GroundingExcerpt,
    ProviderAnswer,
)
from legal_chatbot.chat.errors import ProviderOutputFailureClass
from legal_chatbot.chat.models import classify_provider_answer_safety
from legal_chatbot.retrieval import ResolvedCitation, TemporalScope


def _citation(*, run_id: UUID | None = None) -> ResolvedCitation:
    return ResolvedCitation(
        citation_id=uuid4(),
        retrieval_run_id=run_id if run_id is not None else uuid4(),
        document_chunk_id=uuid4(),
        document_version_id=uuid4(),
        document_id=uuid4(),
        source_provenance_record_id=uuid4(),
        source_id="VBQPPL",
        external_id="123",
    )


def test_request_normalizes_nfc_is_bounded_and_frozen() -> None:
    request = ChatRequest(question="  ca\u0300 phe\u0302  ", temporal_scope=TemporalScope.NONE)

    assert request.question == "cà phê"
    with pytest.raises(ValidationError, match="invalid"):
        ChatRequest(question=" \t ")
    with pytest.raises(ValidationError):
        ChatRequest(question="x" * (QUESTION_MAX_CHARS + 1))
    with pytest.raises(ValidationError):
        request.question = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        ChatRequest(question="question", unsafe="value")  # type: ignore[call-arg]


def test_request_optional_retrieval_query_and_generic_context_are_bounded_and_frozen() -> None:
    context = ConversationContext(
        rolling_summary="  ca\u0300 phe\u0302  ",
        active_topic="  topic  ",
        recent_turns=(
            ConversationContextTurn(role="USER", text="  first  ", ordinal=1),
            ConversationContextTurn(role="ASSISTANT", text="  second  ", ordinal=3),
        ),
    )
    request = ChatRequest(
        question="current question",
        retrieval_query="  ca\u0300 phe\u0302 query  ",
        conversation_context=context,
    )

    assert request.retrieval_query == "cà phê query"
    assert context.rolling_summary == "cà phê"
    assert context.active_topic == "topic"
    assert tuple(turn.text for turn in context.recent_turns) == ("first", "second")
    assert ChatRequest(question="question").retrieval_query is None
    assert ChatRequest(question="question").conversation_context is None
    with pytest.raises(ValidationError, match="invalid"):
        ChatRequest(question="question", retrieval_query=" \t ")
    with pytest.raises(ValidationError):
        ChatRequest(question="question", retrieval_query="x" * (QUESTION_MAX_CHARS + 1))
    with pytest.raises(ValidationError):
        request.retrieval_query = "changed"  # type: ignore[misc]


def test_conversation_context_validates_roles_ordinals_bounds_and_safe_errors() -> None:
    assert CONVERSATION_CONTEXT_MAX_CHARS == 1_000
    assert CONVERSATION_CONTEXT_TURN_LIMIT == 4
    with pytest.raises(ValidationError):
        ConversationContextTurn(role="SYSTEM", text="text", ordinal=1)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="invalid"):
        ConversationContextTurn(role="USER", text=" ", ordinal=1)
    with pytest.raises(ValidationError):
        ConversationContextTurn(role="USER", text="x" * 4_001, ordinal=1)
    with pytest.raises(ValidationError):
        ConversationContextTurn(role="USER", text="text", ordinal=0)
    with pytest.raises(ValidationError, match="ordinals"):
        ConversationContext(
            recent_turns=(
                ConversationContextTurn(role="USER", text="first", ordinal=2),
                ConversationContextTurn(role="ASSISTANT", text="second", ordinal=2),
            )
        )
    with pytest.raises(ValidationError):
        ConversationContext(
            recent_turns=tuple(
                ConversationContextTurn(role="USER", text="turn", ordinal=index)
                for index in range(1, 6)
            )
        )
    sentinel = "CONTEXT_SENTINEL_DO_NOT_ECHO"
    with pytest.raises(ValidationError) as error:
        ConversationContext(rolling_summary=sentinel + "x" * 1_500)
    assert sentinel not in str(error.value)
    with pytest.raises(ValidationError, match="allowed bound"):
        ConversationContext(
            rolling_summary="s" * 800,
            recent_turns=(ConversationContextTurn(role="USER", text="t" * 201, ordinal=1),),
        )


def test_grounding_contracts_enforce_all_evidence_bounds_and_run_invariants() -> None:
    run_id = uuid4()
    citation = _citation(run_id=run_id)
    request = GroundingEvidenceRequest(
        retrieval_run_id=run_id, citation_ids=(citation.citation_id,)
    )
    excerpt = GroundingExcerpt(citation=citation, text="  excerpt  ")
    evidence = GroundingEvidence(retrieval_run_id=run_id, excerpts=(excerpt,))

    assert request.citation_ids == (citation.citation_id,)
    assert evidence.excerpts[0].text == "excerpt"
    with pytest.raises(ValidationError, match="unique"):
        GroundingEvidenceRequest(
            retrieval_run_id=run_id, citation_ids=(citation.citation_id, citation.citation_id)
        )
    with pytest.raises(ValidationError):
        GroundingEvidenceRequest(
            retrieval_run_id=run_id, citation_ids=tuple(uuid4() for _ in range(7))
        )
    with pytest.raises(ValidationError):
        GroundingExcerpt(citation=citation, text="x" * (EXCERPT_MAX_CHARS + 1))
    with pytest.raises(ValidationError, match="match"):
        GroundingEvidence(
            retrieval_run_id=uuid4(), excerpts=(GroundingExcerpt(citation=citation, text="x"),)
        )
    duplicate = GroundingExcerpt(citation=citation, text="different")
    with pytest.raises(ValidationError, match="unique"):
        GroundingEvidence(retrieval_run_id=run_id, excerpts=(excerpt, duplicate))

    excerpts = tuple(
        GroundingExcerpt(citation=_citation(run_id=run_id), text="x" * 2_000) for _ in range(3)
    )
    assert GroundingEvidence(retrieval_run_id=run_id, excerpts=excerpts)
    oversized_excerpt = GroundingExcerpt.model_construct(
        citation=_citation(run_id=run_id), text="x" * 2_001
    )
    with pytest.raises(ValidationError, match="total evidence"):
        GroundingEvidence(
            retrieval_run_id=run_id,
            excerpts=(
                oversized_excerpt,
                GroundingExcerpt(citation=_citation(run_id=run_id), text="x" * 2_000),
                GroundingExcerpt(citation=_citation(run_id=run_id), text="x" * 2_000),
            ),
        )
    assert TOTAL_EVIDENCE_MAX_CHARS == 6_000


@pytest.mark.parametrize(
    "unsafe_answer",
    [
        "\n",
        "http:unsafe",
        "http://example.test",
        "https:unsafe",
        "https://example.test",
        "ftp:unsafe",
        "ftp://example.test",
        "mailto:test@example.test",
        "FILE:/tmp/evidence",
        "DATA:text/plain,unsafe",
        "JAVASCRIPT:unsafe()",
        "tel:+84901234567",
        str(uuid4()),
        "[E1] text",
        "E1",
        "See E12.",
        "citation_id",
    ],
)
def test_provider_answer_rejects_unsafe_values_without_echoing_them(unsafe_answer: str) -> None:
    with pytest.raises(ValidationError) as error:
        ProviderAnswer(answer=unsafe_answer)

    if unsafe_answer.strip():
        assert unsafe_answer not in str(error.value)
    assert ProviderAnswer(answer="  ca\u0300 phe\u0302  ").answer == "cà phê"
    with pytest.raises(ValidationError):
        ProviderAnswer(answer="x" * (ANSWER_MAX_CHARS + 1))


@pytest.mark.parametrize(
    ("unsafe_answer", "failure_class"),
    [
        ("bad\u0001control", ProviderOutputFailureClass.ANSWER_CONTROL),
        ("https://example.test", ProviderOutputFailureClass.ANSWER_URL),
        ("00000000-0000-0000-0000-000000000001", ProviderOutputFailureClass.ANSWER_UUID),
        ("[E1]", ProviderOutputFailureClass.ANSWER_EVIDENCE_TOKEN),
        ("citation_id", ProviderOutputFailureClass.ANSWER_CITATION_ID),
    ],
)
def test_provider_answer_safety_classifier_matches_pydantic_rejection(
    unsafe_answer: str, failure_class: ProviderOutputFailureClass
) -> None:
    assert classify_provider_answer_safety(unsafe_answer) is failure_class
    with pytest.raises(ValidationError):
        ProviderAnswer(answer=unsafe_answer)


def test_provider_answer_safety_classifier_uses_documented_precedence() -> None:
    unsafe_answer = (
        "\u0001https://example.test 00000000-0000-0000-0000-000000000001 [E1] citation_id"
    )

    assert (
        classify_provider_answer_safety(unsafe_answer)
        is ProviderOutputFailureClass.ANSWER_CONTROL
    )


@pytest.mark.parametrize(
    "formatted_answer",
    [
        "First paragraph.\nSecond paragraph.",
        "First paragraph.\r\nSecond paragraph.",
        "Term\tDefinition",
    ],
)
def test_provider_answer_allows_ordinary_formatting_controls(formatted_answer: str) -> None:
    assert classify_provider_answer_safety(formatted_answer) is None
    assert ProviderAnswer(answer=formatted_answer).answer == formatted_answer


@pytest.mark.parametrize(
    "unsafe_answer",
    [
        "safe\x00unsafe",
        "safe\x1bunsafe",
        "safe\u202eunsafe",
        "safe\ud800unsafe",
        "safe\ue000unsafe",
        "safe\u0378unsafe",
        "safe\nformatting\tand\x00unsafe",
    ],
)
def test_provider_answer_rejects_every_disallowed_control_category(unsafe_answer: str) -> None:
    assert (
        classify_provider_answer_safety(unsafe_answer) is ProviderOutputFailureClass.ANSWER_CONTROL
    )
    with pytest.raises(ValidationError):
        ProviderAnswer(answer=unsafe_answer)


@pytest.mark.parametrize("ordinary_prose", ["Note: the rule applies.", "Article: 1 applies."])
def test_provider_answer_allows_ordinary_colon_prose(ordinary_prose: str) -> None:
    assert ProviderAnswer(answer=ordinary_prose).answer == ordinary_prose


def test_policy_decision_invariants_are_fail_closed() -> None:
    assert ChatPolicyDecision(
        outcome=ChatOutcome.ANSWER,
        reason=ChatReasonCode.ANSWER_ELIGIBLE,
        provider_allowed=True,
    )
    assert ChatPolicyDecision(
        outcome=ChatOutcome.CLARIFICATION,
        reason=ChatReasonCode.NO_RESULTS,
        provider_allowed=False,
        fixed_text="clarify",
    )
    assert ChatPolicyDecision(
        outcome=ChatOutcome.REFUSAL,
        reason=ChatReasonCode.GROUNDING_FAILURE,
        provider_allowed=False,
        fixed_text="refuse",
    )
    with pytest.raises(ValidationError):
        ChatPolicyDecision(
            outcome=ChatOutcome.ANSWER,
            reason=ChatReasonCode.ANSWER_ELIGIBLE,
            provider_allowed=False,
        )
    with pytest.raises(ValidationError):
        ChatPolicyDecision(
            outcome=ChatOutcome.ANSWER,
            reason=ChatReasonCode.ANSWER_GROUNDED,
            provider_allowed=True,
        )
    with pytest.raises(ValidationError):
        ChatPolicyDecision(
            outcome=ChatOutcome.REFUSAL,
            reason=ChatReasonCode.NO_RESULTS,
            provider_allowed=False,
            fixed_text="refuse",
        )


def test_grounded_result_enforces_all_outcome_routes_and_citation_runs() -> None:
    run_id = uuid4()
    citation = _citation(run_id=run_id)
    answer = GroundedChatResult(
        outcome=ChatOutcome.ANSWER,
        reason=ChatReasonCode.ANSWER_GROUNDED,
        answer="answer",
        retrieval_run_id=run_id,
        citations=(citation,),
        provider="provider",
        model="model",
        provider_request_id="request-123",
    )
    assert answer.citations == (citation,)
    assert answer.provider_request_id == "request-123"
    assert GroundedChatResult(
        outcome=ChatOutcome.CLARIFICATION,
        reason=ChatReasonCode.NO_RESULTS,
        answer="clarify",
        retrieval_run_id=run_id,
    )
    assert GroundedChatResult(
        outcome=ChatOutcome.REFUSAL,
        reason=ChatReasonCode.RETRIEVAL_FAILURE,
        answer="refuse",
    )
    with pytest.raises(ValidationError):
        GroundedChatResult(
            outcome=ChatOutcome.ANSWER,
            reason=ChatReasonCode.ANSWER_ELIGIBLE,
            answer="answer",
            retrieval_run_id=run_id,
            citations=(citation,),
            provider="provider",
            model="model",
        )
    with pytest.raises(ValidationError):
        GroundedChatResult(
            outcome=ChatOutcome.CLARIFICATION,
            reason=ChatReasonCode.NO_RESULTS,
            answer="clarify",
            retrieval_run_id=run_id,
            provider="provider",
        )
    with pytest.raises(ValidationError):
        GroundedChatResult(
            outcome=ChatOutcome.REFUSAL,
            reason=ChatReasonCode.GROUNDING_FAILURE,
            answer="refuse",
        )
    assert GroundedChatResult(
        outcome=ChatOutcome.REFUSAL,
        reason=ChatReasonCode.GROUNDING_FAILURE,
        answer="refuse",
        retrieval_run_id=run_id,
    )
    with pytest.raises(ValidationError, match="match"):
        GroundedChatResult(
            outcome=ChatOutcome.ANSWER,
            reason=ChatReasonCode.ANSWER_GROUNDED,
            answer="answer",
            retrieval_run_id=run_id,
            citations=(_citation(),),
            provider="provider",
            model="model",
        )


@pytest.mark.parametrize(
    "reason",
    [
        ChatReasonCode.UNSUPPORTED_TEMPORAL_SCOPE,
        ChatReasonCode.INVALID_EVIDENCE_CHAIN,
        ChatReasonCode.GROUNDING_FAILURE,
        ChatReasonCode.PROVIDER_FAILURE,
        ChatReasonCode.INVALID_PROVIDER_OUTPUT,
        ChatReasonCode.CITATION_REVALIDATION_FAILURE,
    ],
)
def test_non_retrieval_failure_refusals_require_a_retrieval_run(reason: ChatReasonCode) -> None:
    with pytest.raises(ValidationError):
        GroundedChatResult(outcome=ChatOutcome.REFUSAL, reason=reason, answer="refuse")


@pytest.mark.parametrize("unsafe_request_id", ["unsafe request", "unsafe\nrequest", "x" * 129])
def test_grounded_result_rejects_unsafe_provider_request_ids_without_echoing_them(
    unsafe_request_id: str,
) -> None:
    run_id = uuid4()
    with pytest.raises(ValidationError) as error:
        GroundedChatResult(
            outcome=ChatOutcome.ANSWER,
            reason=ChatReasonCode.ANSWER_GROUNDED,
            answer="answer",
            retrieval_run_id=run_id,
            citations=(_citation(run_id=run_id),),
            provider="provider",
            model="model",
            provider_request_id=unsafe_request_id,
        )

    assert unsafe_request_id not in str(error.value)


@pytest.mark.parametrize("outcome", [ChatOutcome.CLARIFICATION, ChatOutcome.REFUSAL])
@pytest.mark.parametrize(
    "provider_metadata",
    [{"provider": "provider"}, {"model": "model"}, {"provider_request_id": "request-123"}],
)
def test_non_provider_results_reject_provider_metadata(
    outcome: ChatOutcome, provider_metadata: dict[str, str]
) -> None:
    if outcome is ChatOutcome.CLARIFICATION:
        reason = ChatReasonCode.NO_RESULTS
        retrieval_run_id = uuid4()
    else:
        reason = ChatReasonCode.RETRIEVAL_FAILURE
        retrieval_run_id = None

    result_input: dict[str, object] = {
        "outcome": outcome,
        "reason": reason,
        "answer": "response",
        "retrieval_run_id": retrieval_run_id,
    }
    result_input.update(provider_metadata)
    with pytest.raises(ValidationError):
        GroundedChatResult.model_validate(result_input)
