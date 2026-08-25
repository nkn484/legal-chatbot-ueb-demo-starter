"""Bounded provider-neutral contracts for P2 legal-question analysis."""

from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from legal_chatbot.legal_evidence.models import (
    AnalysisOrigin,
    AnalyzerOutcome,
    LegalQuestionAnalysisResult,
    PreferredSourceTier,
    QuestionAnalysis,
    SubIntent,
)

_DOCUMENT_NUMBER_RE = re.compile(
    r"\b\d{1,5}/(?:\d{2,4}/)?[0-9A-Za-zÀ-ÖØ-öø-ỹĐđ]+(?:[-.][0-9A-Za-zÀ-ÖØ-öø-ỹĐđ]+){0,3}\b",
    re.UNICODE,
)
_MAX_VALUE_CHARS = 256
_MAX_SUB_INTENTS = 4
LEGAL_QUESTION_ANALYZER_VERSION = "p2-legal-question-analyzer-v1"


class _FrozenAnalyzerModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LegalQuestionAnalyzerSettings(_FrozenAnalyzerModel):
    """Default-off settings with no environment or runtime composition wiring."""

    enabled: bool = False
    deterministic_first: bool = True
    max_output_tokens: int = Field(default=512, ge=64, le=1_024)
    prompt_max_chars: int = Field(default=8_000, ge=512, le=16_000)
    timeout_seconds: float = Field(default=3.0, gt=0, le=30)


def _proposal_text(value: str, *, maximum: int = _MAX_VALUE_CHARS) -> str:
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError("analysis proposal text must be nonblank and bounded")
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise ValueError("analysis proposal text contains a control character")
    if _DOCUMENT_NUMBER_RE.search(normalized):
        raise ValueError("analysis proposals cannot contain document identifiers")
    return normalized


class LegalSubIntentProposal(_FrozenAnalyzerModel):
    """One LLM proposal; it contains no legal conclusion or evidence identity."""

    description: str = Field(min_length=1, max_length=512, exclude=True, repr=False)
    retrieval_concepts: tuple[str, ...] = Field(default=(), max_length=8, exclude=True, repr=False)
    preferred_source_tiers: tuple[PreferredSourceTier, ...] = Field(
        default=(), max_length=3, exclude=True, repr=False
    )

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        return _proposal_text(value, maximum=512)

    @field_validator("retrieval_concepts")
    @classmethod
    def validate_concepts(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("sub-intent concepts must be unique")
        return tuple(_proposal_text(item) for item in value)

    @field_validator("preferred_source_tiers")
    @classmethod
    def validate_source_tiers(
        cls, value: tuple[PreferredSourceTier, ...]
    ) -> tuple[PreferredSourceTier, ...]:
        if len(set(value)) != len(value):
            raise ValueError("sub-intent source tiers must be unique")
        return value

    def to_sub_intent(self) -> SubIntent:
        return SubIntent(
            description=self.description,
            retrieval_concepts=self.retrieval_concepts,
            preferred_source_tiers=self.preferred_source_tiers,
        )


class LegalQuestionAnalysisProposal(_FrozenAnalyzerModel):
    """Strict P2 model output with only proposal-level fields."""

    main_intent: str = Field(min_length=1, max_length=256, exclude=True, repr=False)
    legal_actor: str | None = Field(default=None, max_length=128, exclude=True, repr=False)
    legal_action_event: str | None = Field(default=None, max_length=128, exclude=True, repr=False)
    explicit_time: tuple[str, ...] = Field(default=(), max_length=4, exclude=True, repr=False)
    legal_topics: tuple[str, ...] = Field(default=(), max_length=4, exclude=True, repr=False)
    ambiguity: bool = False
    sub_intents: tuple[LegalSubIntentProposal, ...] = Field(
        min_length=1, max_length=_MAX_SUB_INTENTS, exclude=True, repr=False
    )
    preferred_source_tiers: tuple[PreferredSourceTier, ...] = Field(
        default=(), max_length=3, exclude=True, repr=False
    )
    retrieval_concepts: tuple[str, ...] = Field(default=(), max_length=8, exclude=True, repr=False)

    @field_validator("main_intent")
    @classmethod
    def validate_main_intent(cls, value: str) -> str:
        return _proposal_text(value)

    @field_validator("legal_actor", "legal_action_event")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        return None if value is None else _proposal_text(value, maximum=128)

    @field_validator("explicit_time", "legal_topics", "retrieval_concepts")
    @classmethod
    def validate_text_tuples(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("analysis proposal values must be unique")
        return tuple(_proposal_text(item) for item in value)

    @field_validator("preferred_source_tiers")
    @classmethod
    def validate_source_tiers(
        cls, value: tuple[PreferredSourceTier, ...]
    ) -> tuple[PreferredSourceTier, ...]:
        if len(set(value)) != len(value):
            raise ValueError("preferred source tiers must be unique")
        return value

    @model_validator(mode="after")
    def validate_distinct_sub_intents(self) -> LegalQuestionAnalysisProposal:
        descriptions = tuple(item.description.casefold() for item in self.sub_intents)
        if len(set(descriptions)) != len(descriptions):
            raise ValueError("sub-intent descriptions must be unique")
        return self

    def to_result(self) -> LegalQuestionAnalysisResult:
        return LegalQuestionAnalysisResult(
            analysis=QuestionAnalysis(
                origin=AnalysisOrigin.LLM_PROPOSAL,
                main_intent=self.main_intent,
                legal_actor=self.legal_actor,
                legal_action_event=self.legal_action_event,
                explicit_time=self.explicit_time,
                legal_topics=self.legal_topics,
                preferred_source_tiers=self.preferred_source_tiers,
                retrieval_concepts=self.retrieval_concepts,
                ambiguous=self.ambiguity,
            ),
            sub_intents=tuple(item.to_sub_intent() for item in self.sub_intents),
            outcome=AnalyzerOutcome.LLM_ANALYSIS,
        )


__all__ = [
    "LEGAL_QUESTION_ANALYZER_VERSION",
    "LegalQuestionAnalysisProposal",
    "LegalQuestionAnalyzerSettings",
    "LegalSubIntentProposal",
]
