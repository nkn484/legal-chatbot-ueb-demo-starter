"""Deterministic, channel-neutral policy helpers for conversation contracts."""

from collections.abc import Iterable
from hashlib import sha256
from typing import Final
from unicodedata import category, normalize

from pydantic import ValidationError

from legal_chatbot.chat.models import (
    CONVERSATION_CONTEXT_MAX_CHARS,
    CONVERSATION_CONTEXT_TURN_LIMIT,
    ChatRequest,
    ConversationContext,
    ConversationContextTurn,
)
from legal_chatbot.conversation.errors import ConversationError, ConversationErrorCode
from legal_chatbot.conversation.models import (
    ACTIVE_TOPIC_MAX_CHARS,
    DELIVERY_ID_MAX_CHARS,
    ROLLING_SUMMARY_MAX_CHARS,
    USER_TEXT_MAX_CHARS,
    ConversationCompactionCandidate,
    ConversationReferenceKind,
    ConversationRequest,
    ConversationReservation,
    ConversationStateSnapshot,
    ConversationStateUpdate,
    ConversationTurn,
)

_ACTIVE_TOPIC_LABEL = "\nActive topic: "
_COMPACTION_SEPARATOR = " | "
_COMPACTION_SNIPPET_MAX_CHARS: Final = 160


def _normalize(value: object, *, max_chars: int, code: ConversationErrorCode) -> str:
    """Normalize untrusted text or raise a code-only conversation error."""

    if not isinstance(value, str):
        raise ConversationError(code)
    normalized = normalize("NFC", value).strip()
    if (
        not normalized
        or len(normalized) > max_chars
        or any(category(character).startswith("C") for character in normalized)
    ):
        raise ConversationError(code)
    return normalized


def normalize_delivery_id(delivery_id: object) -> str:
    """Return the bounded canonical delivery identifier without retaining raw variants."""

    return _normalize(
        delivery_id,
        max_chars=DELIVERY_ID_MAX_CHARS,
        code=ConversationErrorCode.DELIVERY_INVALID,
    )


def delivery_key_sha256(delivery_id: object) -> str:
    """Return the lowercase SHA-256 key for a normalized delivery identifier."""

    return sha256(normalize_delivery_id(delivery_id).encode("utf-8")).hexdigest()


def derive_retrieval_query(current_text: object, active_topic: object | None) -> str:
    """Keep current text intact and append a topic label only when it fits safely."""

    text = _normalize(
        current_text,
        max_chars=USER_TEXT_MAX_CHARS,
        code=ConversationErrorCode.DELIVERY_INVALID,
    )
    if active_topic is None:
        return text
    topic = _normalize(
        active_topic,
        max_chars=ACTIVE_TOPIC_MAX_CHARS,
        code=ConversationErrorCode.STATE_INVALID,
    )
    candidate = f"{text}{_ACTIVE_TOPIC_LABEL}{topic}"
    if len(candidate) > USER_TEXT_MAX_CHARS:
        return text
    return candidate


def to_chat_context(snapshot: ConversationStateSnapshot) -> ConversationContext:
    """Map bounded state to generic M06 context, deliberately omitting references."""

    if not isinstance(snapshot, ConversationStateSnapshot):
        raise ConversationError(ConversationErrorCode.STATE_INVALID)
    if len(snapshot.recent_turns) > CONVERSATION_CONTEXT_TURN_LIMIT:
        raise ConversationError(ConversationErrorCode.STATE_INVALID)
    try:
        context_length = sum(
            len(value)
            for value in (
                snapshot.rolling_summary,
                snapshot.active_topic,
                *(turn.text for turn in snapshot.recent_turns),
            )
            if value is not None
        )
        if context_length > CONVERSATION_CONTEXT_MAX_CHARS:
            raise ConversationError(ConversationErrorCode.STATE_INVALID)
        return ConversationContext(
            rolling_summary=snapshot.rolling_summary,
            active_topic=snapshot.active_topic,
            recent_turns=tuple(
                ConversationContextTurn(
                    role=turn.role.value,
                    text=turn.text,
                    ordinal=turn.ordinal,
                )
                for turn in snapshot.recent_turns
            ),
        )
    except (AttributeError, TypeError, ValidationError):
        raise ConversationError(ConversationErrorCode.STATE_INVALID) from None


def derive_active_topic(current_text: object, settings: object) -> str:
    """Return a deterministic normalized text prefix, never a legal classification."""

    text = _normalize(
        current_text,
        max_chars=USER_TEXT_MAX_CHARS,
        code=ConversationErrorCode.DELIVERY_INVALID,
    )
    return text[: _setting_int(settings, "active_topic_max_chars")]


def summarize_compacted(
    existing_summary: object | None, candidates: Iterable[object], settings: object
) -> str | None:
    """Append deterministic untrusted-state entries and retain only the newest safe suffix."""

    limit = _setting_int(settings, "rolling_summary_max_chars")
    summary = _safe_optional_summary(existing_summary)
    entries = tuple(_render_compaction_candidate(candidate) for candidate in candidates)
    values = tuple(value for value in (summary, *entries) if value)
    if not values:
        return None
    return _COMPACTION_SEPARATOR.join(values)[-limit:]


def project_chat_context(
    snapshot: ConversationStateSnapshot, rolling_summary: object | None, settings: object
) -> ConversationContext | None:
    """Project bounded state without references, favoring topic then newest turns then summary."""

    if not isinstance(snapshot, ConversationStateSnapshot):
        raise ConversationError(ConversationErrorCode.STATE_INVALID)
    context_limit = _setting_int(settings, "context_max_chars")
    if context_limit > CONVERSATION_CONTEXT_MAX_CHARS:
        raise ConversationError(ConversationErrorCode.STATE_INVALID)
    if len(snapshot.recent_turns) > CONVERSATION_CONTEXT_TURN_LIMIT:
        raise ConversationError(ConversationErrorCode.STATE_INVALID)

    topic = snapshot.active_topic
    if topic is not None and len(topic) > context_limit:
        return None
    remaining = context_limit - (len(topic) if topic is not None else 0)
    selected_reversed: list[ConversationContextTurn] = []
    try:
        for turn in reversed(snapshot.recent_turns):
            if remaining <= 0:
                break
            text = turn.text
            selected_text = text if len(text) <= remaining else text[:remaining]
            if not selected_text:
                break
            selected_reversed.append(
                ConversationContextTurn(
                    role=turn.role.value,
                    text=selected_text,
                    ordinal=turn.ordinal,
                )
            )
            remaining -= len(selected_text)
        summary = _safe_optional_summary(rolling_summary)
        projected_summary = summary[-remaining:] if summary is not None and remaining else None
        if topic is None and not selected_reversed and projected_summary is None:
            return None
        return ConversationContext(
            rolling_summary=projected_summary,
            active_topic=topic,
            recent_turns=tuple(reversed(selected_reversed)),
        )
    except (AttributeError, TypeError, ValidationError):
        raise ConversationError(ConversationErrorCode.STATE_INVALID) from None


def build_chat_request(
    request: ConversationRequest, reservation: ConversationReservation, settings: object
) -> ChatRequest:
    """Build one M06 request from current user input and bounded prior state only."""

    _require_reservation_inputs(request, reservation)
    rolling_summary = _computed_rolling_summary(reservation, settings)
    context = project_chat_context(reservation.snapshot, rolling_summary, settings)
    return ChatRequest(
        question=request.text,
        retrieval_query=derive_retrieval_query(request.text, reservation.snapshot.active_topic),
        conversation_context=context,
        temporal_scope=request.temporal_scope,
    )


def build_state_update(
    reservation: ConversationReservation, request: ConversationRequest, settings: object
) -> ConversationStateUpdate:
    """Build the exact version-bound deterministic update paired with this reservation."""

    _require_reservation_inputs(request, reservation)
    return ConversationStateUpdate(
        expected_state_version=reservation.expected_state_version,
        rolling_summary=_computed_rolling_summary(reservation, settings),
        active_topic=derive_active_topic(request.text, settings),
        compacted_exchange_ids=reservation.compaction_plan.exchange_ids,
    )


def _setting_int(settings: object, field_name: str) -> int:
    """Read a positive configured bound without exposing malformed configuration input."""

    value = getattr(settings, field_name, None)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConversationError(ConversationErrorCode.STATE_INVALID)
    return value


def _safe_optional_summary(value: object | None) -> str | None:
    if value is None:
        return None
    return _normalize(
        value,
        max_chars=ROLLING_SUMMARY_MAX_CHARS,
        code=ConversationErrorCode.STATE_INVALID,
    )


def _render_compaction_candidate(candidate: object) -> str:
    """Render content as untrusted bounded snippets without identifier-bearing metadata."""

    status = _safe_label(getattr(candidate, "status", "COMPLETED"), default="COMPLETED")
    role = _safe_label(getattr(candidate, "role", None), default="NONE")
    outcome = _safe_label(
        getattr(candidate, "chat_outcome", getattr(candidate, "outcome", None)), default="NONE"
    )
    reason = _safe_label(
        getattr(candidate, "chat_reason", getattr(candidate, "reason", None)), default="NONE"
    )
    if isinstance(candidate, ConversationCompactionCandidate):
        citation_count = candidate.citation_count
        document_count = candidate.document_count
    else:
        references = getattr(candidate, "references", ())
        if not isinstance(references, tuple):
            references = ()
        citation_count = sum(
            getattr(reference, "kind", None) is ConversationReferenceKind.CITATION
            for reference in references
        )
        document_count = sum(
            getattr(reference, "kind", None) is ConversationReferenceKind.DOCUMENT
            for reference in references
        )
    user_text = _safe_snippet(getattr(candidate, "user_text", None))
    assistant_text = _safe_snippet(getattr(candidate, "assistant_text", None))
    if user_text is None and assistant_text is None:
        text = _safe_snippet(getattr(candidate, "text", None))
        if role == "USER":
            user_text = text
        else:
            assistant_text = text
    snippets = tuple(
        f"{name}={value}"
        for name, value in (("user", user_text), ("assistant", assistant_text))
        if value is not None
    )
    return "; ".join(
        (
            f"status={status}",
            f"role={role}",
            f"outcome={outcome}",
            f"reason={reason}",
            f"citations={citation_count}",
            f"documents={document_count}",
            *snippets,
        )
    )


def _safe_label(value: object, *, default: str) -> str:
    raw = getattr(value, "value", value)
    if not isinstance(raw, str):
        return default
    normalized = normalize("NFC", raw).strip()
    if not normalized or any(category(character).startswith("C") for character in normalized):
        return default
    return normalized[:64]


def _safe_snippet(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = normalize("NFC", value).strip()
    if not normalized or any(category(character).startswith("C") for character in normalized):
        return "[invalid]"
    return normalized[:_COMPACTION_SNIPPET_MAX_CHARS]


def _computed_rolling_summary(reservation: ConversationReservation, settings: object) -> str | None:
    plan = getattr(reservation, "compaction_plan", None)
    candidates = getattr(plan, "candidates", None)
    if candidates is None:
        candidates = _evicted_turns(reservation.snapshot, settings)
    if not isinstance(candidates, tuple):
        raise ConversationError(ConversationErrorCode.STATE_INVALID)
    return summarize_compacted(reservation.snapshot.rolling_summary, candidates, settings)


def _evicted_turns(
    snapshot: ConversationStateSnapshot, settings: object
) -> tuple[ConversationTurn, ...]:
    baseline = project_chat_context(snapshot, snapshot.rolling_summary, settings)
    if baseline is None:
        return snapshot.recent_turns
    retained = {turn.ordinal: turn.text for turn in baseline.recent_turns}
    return tuple(turn for turn in snapshot.recent_turns if retained.get(turn.ordinal) != turn.text)


def _require_reservation_inputs(
    request: ConversationRequest, reservation: ConversationReservation
) -> None:
    if not isinstance(request, ConversationRequest) or not isinstance(
        reservation, ConversationReservation
    ):
        raise ConversationError(ConversationErrorCode.STATE_INVALID)
