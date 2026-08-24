"""Deterministic policy coverage for M07 Phase 1 conversation helpers."""

from uuid import uuid4

import pytest

from legal_chatbot.chat import ChatOutcome, ChatReasonCode
from legal_chatbot.conversation import (
    ConversationError,
    ConversationErrorCode,
    ConversationReference,
    ConversationReferenceKind,
    ConversationStateSnapshot,
    ConversationTurn,
    ConversationTurnRole,
    delivery_key_sha256,
    derive_retrieval_query,
    normalize_delivery_id,
    to_chat_context,
)
from legal_chatbot.conversation.config import ConversationSettings
from legal_chatbot.conversation.models import (
    ConversationCompactionCandidate,
    ConversationCompactionPlan,
    ConversationExchangeStatus,
    ConversationRequest,
    ConversationReservation,
    ConversationStateUpdate,
)
from legal_chatbot.conversation.policy import (
    build_chat_request,
    build_state_update,
    derive_active_topic,
    project_chat_context,
    summarize_compacted,
)


def _assistant_turn(ordinal: int) -> ConversationTurn:
    return ConversationTurn(
        ordinal=ordinal,
        role=ConversationTurnRole.ASSISTANT,
        text="previous answer",
        outcome=ChatOutcome.CLARIFICATION,
        reason=ChatReasonCode.NO_RESULTS,
    )


def test_delivery_normalization_and_digest_are_deterministic_and_never_retain_raw_input() -> None:
    assert normalize_delivery_id("  ca\u0300 phe\u0302  ") == "cà phê"
    assert delivery_key_sha256("cà phê") == delivery_key_sha256("  ca\u0300 phe\u0302  ")
    assert delivery_key_sha256("delivery").islower()
    with pytest.raises(ConversationError) as error:
        normalize_delivery_id("\x00")
    assert error.value.code is ConversationErrorCode.DELIVERY_INVALID
    assert "\x00" not in str(error.value)


def test_retrieval_query_preserves_current_text_and_only_appends_a_fitting_topic() -> None:
    assert derive_retrieval_query("  ca\u0300 phe\u0302  ", None) == "cà phê"
    assert derive_retrieval_query("question", "topic") == "question\nActive topic: topic"
    current = "x" * 4_000
    assert derive_retrieval_query(current, "topic") == current
    with pytest.raises(ConversationError) as error:
        derive_retrieval_query("x" * 4_001, None)
    assert error.value.code is ConversationErrorCode.DELIVERY_INVALID


def test_context_mapping_preserves_turn_order_and_omits_references() -> None:
    snapshot = ConversationStateSnapshot(
        state_version=2,
        rolling_summary="summary",
        active_topic="topic",
        recent_turns=(
            ConversationTurn(ordinal=1, role=ConversationTurnRole.USER, text="first"),
            _assistant_turn(2),
        ),
        references=(
            ConversationReference(
                kind=ConversationReferenceKind.CITATION, reference_id=uuid4(), ordinal=0
            ),
        ),
    )

    context = to_chat_context(snapshot)

    assert context.rolling_summary == "summary"
    assert context.active_topic == "topic"
    assert [(turn.role, turn.ordinal) for turn in context.recent_turns] == [
        ("USER", 1),
        ("ASSISTANT", 2),
    ]
    assert "references" not in type(context).model_fields


def test_context_mapping_fails_closed_when_snapshot_bypasses_model_bounds() -> None:
    snapshot = ConversationStateSnapshot.model_construct(
        state_version=0,
        rolling_summary="x" * 1_001,
        active_topic=None,
        recent_turns=(),
        references=(),
    )

    with pytest.raises(ConversationError) as error:
        to_chat_context(snapshot)
    assert error.value.code is ConversationErrorCode.STATE_INVALID


def test_phase_three_policy_compacts_untrusted_state_and_prioritizes_context() -> None:
    settings = ConversationSettings(
        active_topic_max_chars=6,
        rolling_summary_max_chars=120,
        context_max_chars=60,
    )
    turns = (
        ConversationTurn(ordinal=1, role=ConversationTurnRole.USER, text="old user context"),
        ConversationTurn(
            ordinal=2,
            role=ConversationTurnRole.ASSISTANT,
            text="new assistant context",
            outcome=ChatOutcome.CLARIFICATION,
            reason=ChatReasonCode.NO_RESULTS,
        ),
    )
    snapshot = ConversationStateSnapshot(
        state_version=2,
        rolling_summary="older summary",
        active_topic="topic",
        recent_turns=turns,
    )

    summary = summarize_compacted(snapshot.rolling_summary, turns, settings)
    context = project_chat_context(snapshot, summary, settings)

    assert derive_active_topic("  question about legal text  ", settings) == "questi"
    assert summary is not None
    assert "reason=NO_RESULTS" in summary
    assert "citations=0" in summary
    assert "\n" not in summary
    assert not any(character.isspace() and character != " " for character in summary)
    assert (
        ConversationStateUpdate(expected_state_version=2, rolling_summary=summary).rolling_summary
        == summary
    )
    assert context is not None
    assert context.active_topic == "topic"
    assert tuple(turn.ordinal for turn in context.recent_turns) == tuple(
        sorted(turn.ordinal for turn in context.recent_turns)
    )
    assert (
        sum(
            len(value)
            for value in (
                context.rolling_summary,
                context.active_topic,
                *(turn.text for turn in context.recent_turns),
            )
            if value is not None
        )
        <= settings.context_max_chars
    )


def test_build_helpers_keep_current_text_separate_from_compacted_prior_state() -> None:
    settings = ConversationSettings(
        active_topic_max_chars=12,
        rolling_summary_max_chars=100,
        context_max_chars=50,
    )
    snapshot = ConversationStateSnapshot(
        state_version=3,
        rolling_summary="prior summary",
        active_topic="prior topic",
        recent_turns=(
            ConversationTurn(ordinal=1, role=ConversationTurnRole.USER, text="old turn" * 8),
        ),
    )
    reservation = ConversationReservation(
        conversation_id=uuid4(),
        exchange_id=uuid4(),
        ordinal=2,
        expected_state_version=3,
        snapshot=snapshot,
    )
    request = ConversationRequest(
        conversation_id=reservation.conversation_id,
        delivery_id="delivery",
        text="CURRENT_TEXT_SENTINEL " + "x" * 100,
    )

    chat_request = build_chat_request(request, reservation, settings)
    state_update = build_state_update(reservation, request, settings)

    assert chat_request.question == request.text
    assert chat_request.retrieval_query == f"{request.text}\nActive topic: prior topic"
    assert chat_request.conversation_context is not None
    assert "CURRENT_TEXT_SENTINEL" not in str(chat_request.conversation_context)
    assert state_update.expected_state_version == reservation.expected_state_version
    assert state_update.rolling_summary == chat_request.conversation_context.rolling_summary or (
        state_update.rolling_summary is not None
    )
    assert state_update.active_topic == request.text[: settings.active_topic_max_chars]


def test_compaction_plan_ids_and_persisted_reference_counts_are_rendered_in_order() -> None:
    settings = ConversationSettings(rolling_summary_max_chars=120)
    oldest_id, newest_id = uuid4(), uuid4()
    candidates = (
        ConversationCompactionCandidate(
            exchange_id=oldest_id,
            ordinal=1,
            status=ConversationExchangeStatus.COMPLETED,
            user_text="oldest user",
            assistant_text="oldest assistant",
            chat_outcome=ChatOutcome.CLARIFICATION,
            chat_reason="NO_RESULTS",
            citation_count=2,
            document_count=1,
        ),
        ConversationCompactionCandidate(
            exchange_id=newest_id,
            ordinal=2,
            status=ConversationExchangeStatus.COMPLETED,
            user_text="newest user",
            assistant_text="newest assistant",
            chat_outcome=ChatOutcome.CLARIFICATION,
            chat_reason="NO_RESULTS",
            citation_count=4,
            document_count=3,
        ),
    )
    plan = ConversationCompactionPlan(exchange_ids=(oldest_id, newest_id), candidates=candidates)
    request = ConversationRequest(conversation_id=uuid4(), delivery_id="delivery", text="question")
    reservation = ConversationReservation(
        conversation_id=request.conversation_id,
        exchange_id=uuid4(),
        ordinal=3,
        expected_state_version=2,
        snapshot=ConversationStateSnapshot(state_version=2),
        compaction_plan=plan,
    )

    unbounded_settings = ConversationSettings(rolling_summary_max_chars=1_500)
    rendered = summarize_compacted(None, candidates, unbounded_settings)
    state_update = build_state_update(reservation, request, settings)

    assert rendered is not None
    assert rendered.index("user=oldest user") < rendered.index("user=newest user")
    assert "citations=2; documents=1" in rendered
    assert "citations=4; documents=3" in rendered
    assert state_update.compacted_exchange_ids == plan.exchange_ids
    assert state_update.rolling_summary is not None
    assert len(state_update.rolling_summary) <= settings.rolling_summary_max_chars


def test_compaction_summary_uses_a_safe_visible_separator_and_bounded_newest_suffix() -> None:
    settings = ConversationSettings(rolling_summary_max_chars=300)
    candidates = (
        ConversationCompactionCandidate(
            exchange_id=uuid4(),
            ordinal=1,
            status=ConversationExchangeStatus.COMPLETED,
            user_text="oldest",
            assistant_text="answer",
            chat_outcome=ChatOutcome.CLARIFICATION,
            chat_reason="NO_RESULTS",
            citation_count=1,
            document_count=2,
        ),
    )

    summary = summarize_compacted("prior", candidates, settings)

    assert summary is not None
    assert " | " in summary
    assert "\n" not in summary
    assert "citations=1; documents=2" in summary
    assert len(summary) <= settings.rolling_summary_max_chars
