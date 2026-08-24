"""Strict, provider-neutral contracts for the bounded retrieval query planner."""

import re
from enum import StrEnum
from typing import Final
from unicodedata import category, normalize

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PLANNER_MAX_INPUT_CHARS: Final = 900
PLANNER_MAX_OUTPUT_TOKENS: Final = 96
PLANNER_MAX_ANCHORS: Final = 2
PLANNER_MAX_PHRASES: Final = 2
PLANNER_MAX_EXPANSION_TERMS: Final = 4
PLANNER_MAX_ITEM_CHARS: Final = 160
PLANNER_MAX_RESPONSE_BYTES: Final = 4_096

_URL_PATTERN: Final = re.compile(r"\b(?:https?|ftp|file|data|javascript|mailto):", re.IGNORECASE)
_UUID_PATTERN: Final = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_METADATA_PATTERN: Final = re.compile(
    r"\b(?:citation(?:_id)?|source(?:_id)?|document(?:_id|_version_id|_chunk_id)?|"
    r"external_id|canonical_url|provenance|retrieval_run(?:_id)?|evidence(?:_id)?|"
    r"vbqppl|vnu|ueb)\b",
    re.IGNORECASE,
)
_QUERY_SYNTAX_PATTERN: Final = re.compile(
    r"(?:\b(?:select|insert|update|delete|drop|alter|create|grant|revoke|from|where|"
    r'union|tsquery|to_tsquery|websearch_to_tsquery)\b|&&|\|\||!!|<->|[;&|!:*`$\\"()])',
    re.IGNORECASE,
)
_INSTRUCTION_PATTERN: Final = re.compile(
    r"\b(?:ignore\s+(?:all\s+)?(?:previous|prior|above)|system\s+prompt|"
    r"developer\s+message|assistant\s*(?:role|message)|follow\s+(?:these\s+)?instructions|"
    r"jailbreak|bypass\s+(?:the\s+)?(?:rules|policy)|output\s+(?:the\s+)?(?:answer|json))\b",
    re.IGNORECASE,
)
_ANSWER_PROSE_PATTERN: Final = re.compile(
    r"\b(?:đây\s+là|câu\s+trả\s+lời|trả\s+lời\s+rằng|the\s+answer|answer\s+is|"
    r"i\s+(?:cannot|can)|tôi\s+(?:không|có\s+thể)|bạn\s+nên|you\s+should|according\s+to)\b",
    re.IGNORECASE,
)
_PROTECTED_IDENTITY_PATTERN: Final = re.compile(
    r"(?ix)\b(?:"
    r"(?:bộ\s+luật|luật|nghị\s+định|thông\s+tư|quyết\s+định|nghị\s+quyết|"
    r"chỉ\s+thị|pháp\s+lệnh|công\s+văn|công\s+điện|thông\s+báo|kết\s+luận|"
    r"quy\s+chế|văn\s+bản)\b[^,;]{0,120}|"
    r"số\s+\d{1,6}(?:[/-][a-z0-9đ-]+){0,3}|"
    r"\d{1,4}/\d{4}/[a-z0-9-]{2,32}|\d{1,5}/[a-zđ][a-z0-9-]{1,32}|"
    r"(?:điều|khoản|điểm)\s+[a-z0-9]+(?:\s+(?:điều|khoản|điểm)\s+[a-z0-9]+){0,2}|"
    r"(?:bộ|sở|cục|tổng\s+cục|hội\s+đồng|ủy\s+ban|chính\s+phủ|quốc\s+hội|"
    r"tòa\s+án|viện\s+kiểm\s+sát)\b[^,;]{0,80}|"
    r"(?:ngày\s+\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+\d{4}|"
    r"\d{1,2}/\d{1,2}/\d{4}|tháng\s+\d{1,2}\s+năm\s+\d{4}|năm\s+\d{4}|"
    r"có\s+hiệu\s+lực|còn\s+hiệu\s+lực|hết\s+hiệu\s+lực(?:\s+một\s+phần)?|"
    r"đang\s+hiệu\s+lực|ngưng\s+hiệu\s+lực|đình\s+chỉ\s+hiệu\s+lực)"
    r")",
)


def normalize_planner_text(value: str) -> str:
    """NFC-normalize and collapse ordinary whitespace without retaining controls."""

    return " ".join(normalize("NFC", value).split())


def _is_safe_item(value: str) -> bool:
    return not (
        not value
        or len(value) > PLANNER_MAX_ITEM_CHARS
        or any(category(character).startswith("C") for character in value)
        or _URL_PATTERN.search(value) is not None
        or _UUID_PATTERN.search(value) is not None
        or _METADATA_PATTERN.search(value) is not None
        or _QUERY_SYNTAX_PATTERN.search(value) is not None
        or _INSTRUCTION_PATTERN.search(value) is not None
        or _ANSWER_PROSE_PATTERN.search(value) is not None
    )


class _FrozenPlannerModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class QueryPlannerPlan(_FrozenPlannerModel):
    """Validated provider decomposition; it deliberately has no canonical identities."""

    anchor_mentions: tuple[str, ...] = Field(default=(), max_length=PLANNER_MAX_ANCHORS)
    key_phrases: tuple[str, ...] = Field(default=(), max_length=PLANNER_MAX_PHRASES)
    expansion_terms: tuple[str, ...] = Field(default=(), max_length=PLANNER_MAX_EXPANSION_TERMS)

    @field_validator("anchor_mentions", "key_phrases", "expansion_terms", mode="before")
    @classmethod
    def normalize_items(cls, value: object) -> object:
        if not isinstance(value, (list, tuple)):
            return value
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("planner item is invalid")
            if any(category(character).startswith("C") for character in item):
                raise ValueError("planner item is invalid")
            item = normalize_planner_text(item)
            if not _is_safe_item(item):
                raise ValueError("planner item is invalid")
            normalized.append(item)
        return tuple(normalized)

    @model_validator(mode="after")
    def reject_duplicate_items(self) -> "QueryPlannerPlan":
        values = (*self.anchor_mentions, *self.key_phrases, *self.expansion_terms)
        if len(set(value.casefold() for value in values)) != len(values):
            raise ValueError("planner items must be unique")
        return self


class QueryPlannerOutcome(StrEnum):
    """Content-free planner outcomes permitted in structured logs."""

    DISABLED = "DISABLED"
    SKIPPED_TEMPORAL = "SKIPPED_TEMPORAL"
    SKIPPED_INPUT = "SKIPPED_INPUT"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    UNRESOLVED_ANCHOR = "UNRESOLVED_ANCHOR"
    NO_EXPANSION = "NO_EXPANSION"
    PLANNED = "PLANNED"


class QueryPlannerResult(_FrozenPlannerModel):
    """The in-memory planner result; plan contents are never logged or persisted."""

    outcome: QueryPlannerOutcome
    plan: QueryPlannerPlan | None = None

    @model_validator(mode="after")
    def require_plan_only_for_valid_output(self) -> "QueryPlannerResult":
        if (self.outcome is QueryPlannerOutcome.PLANNED) != (self.plan is not None):
            raise ValueError("planner result is invalid")
        return self


def has_protected_identity_drift(value: str, question: str) -> bool:
    """Reject legal identities unless their normalized form is literally in the input."""

    normalized_question = normalize_planner_text(question).casefold()
    return any(
        normalize_planner_text(match.group(0)).casefold() not in normalized_question
        for match in _PROTECTED_IDENTITY_PATTERN.finditer(normalize_planner_text(value))
    )


def validate_query_plan(
    plan: QueryPlannerPlan,
    question: str,
    *,
    max_phrases: int = PLANNER_MAX_PHRASES,
    max_expansion_terms: int = PLANNER_MAX_EXPANSION_TERMS,
) -> QueryPlannerPlan:
    """Apply request-bound semantic checks after strict JSON parsing or port return."""

    if not isinstance(plan, QueryPlannerPlan):
        raise ValueError("planner plan is invalid")
    normalized_question = normalize_planner_text(question).casefold()
    if not normalized_question or len(normalized_question) > PLANNER_MAX_INPUT_CHARS:
        raise ValueError("planner input is invalid")
    validated = QueryPlannerPlan.model_validate(plan.model_dump())
    if (
        len(validated.key_phrases) > max_phrases
        or len(validated.expansion_terms) > max_expansion_terms
        or any(anchor.casefold() not in normalized_question for anchor in validated.anchor_mentions)
        or any(
            has_protected_identity_drift(item, normalized_question)
            for item in (
                *validated.anchor_mentions,
                *validated.key_phrases,
                *validated.expansion_terms,
            )
        )
    ):
        raise ValueError("planner plan is invalid")
    return validated
