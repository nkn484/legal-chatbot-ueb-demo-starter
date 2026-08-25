"""Pure request-scoped legal-evidence contracts.

The models deliberately separate evidence-backed facts from model proposals. They
contain no runtime, persistence, source, channel, or provider imports.
"""

from __future__ import annotations

import unicodedata
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_MAX_SUB_INTENTS = 4
_MAX_CANDIDATES = 30
_MAX_FAMILIES = 15
_MAX_RELATIONS = 30
_MAX_EVIDENCE_UNITS = 20


class _FrozenLegalEvidenceModel(BaseModel):
    """Immutable contract base that rejects accidental runtime payloads."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class LegalTruthCategory(StrEnum):
    """Ownership category for legal assertions in the request context."""

    DETERMINISTIC_FACT = "DETERMINISTIC_FACT"
    LLM_PROPOSAL = "LLM_PROPOSAL"
    VERIFIED_INTERPRETATION = "VERIFIED_INTERPRETATION"


class AuthorityRole(StrEnum):
    GOVERNING = "GOVERNING"
    IMPLEMENTING = "IMPLEMENTING"
    SUPPLEMENTARY = "SUPPLEMENTARY"
    BACKGROUND = "BACKGROUND"
    IRRELEVANT = "IRRELEVANT"


class AuthorityState(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    FILTERED_PROVENANCE = "FILTERED_PROVENANCE"
    FILTERED_SCOPE = "FILTERED_SCOPE"
    FILTERED_STATUS = "FILTERED_STATUS"
    FILTERED_SOURCE_BINDING = "FILTERED_SOURCE_BINDING"
    NOT_RETRIEVED = "NOT_RETRIEVED"
    NOT_IN_CATALOG = "NOT_IN_CATALOG"
    QUARANTINED = "QUARANTINED"


class ApplicabilityState(StrEnum):
    VERIFIED = "VERIFIED"
    METADATA_CURRENT = "METADATA_CURRENT"
    CURRENT_EFFECT_UNVERIFIED = "CURRENT_EFFECT_UNVERIFIED"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"


class CoverageState(StrEnum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    CONFLICT = "CONFLICT"


class RelationType(StrEnum):
    AMENDS = "AMENDS"
    REPLACES = "REPLACES"
    REPEALS = "REPEALS"
    IMPLEMENTS = "IMPLEMENTS"
    GOVERNS = "GOVERNS"


class RelationVerification(StrEnum):
    HINT_ONLY = "HINT_ONLY"
    EVIDENCE_VERIFIED = "EVIDENCE_VERIFIED"
    REVIEWED = "REVIEWED"
    REJECTED = "REJECTED"


class CaseStage(StrEnum):
    RECEIVED = "RECEIVED"
    ANALYZED = "ANALYZED"
    DISCOVERED = "DISCOVERED"
    AUTHORITY_REVIEWED = "AUTHORITY_REVIEWED"
    FAMILIES_RESOLVED = "FAMILIES_RESOLVED"
    EVIDENCE_READ = "EVIDENCE_READ"
    COVERAGE_REVIEWED = "COVERAGE_REVIEWED"
    REPAIRED = "REPAIRED"
    EVIDENCE_SELECTED = "EVIDENCE_SELECTED"
    ANSWER_DRAFTED = "ANSWER_DRAFTED"
    ANSWER_REVIEWED = "ANSWER_REVIEWED"


class AnalysisOrigin(StrEnum):
    DETERMINISTIC_FALLBACK = "DETERMINISTIC_FALLBACK"
    LLM_PROPOSAL = "LLM_PROPOSAL"


class AnalyzerOutcome(StrEnum):
    LLM_ANALYSIS = "LLM_ANALYSIS"
    FALLBACK_DISABLED = "FALLBACK_DISABLED"
    FALLBACK_PROVIDER_UNAVAILABLE = "FALLBACK_PROVIDER_UNAVAILABLE"
    FALLBACK_PROVIDER_FAILURE = "FALLBACK_PROVIDER_FAILURE"
    FALLBACK_INVALID_OUTPUT = "FALLBACK_INVALID_OUTPUT"


class PreferredSourceTier(StrEnum):
    """A retrieval preference proposal, never an authority or access assertion."""

    VBQPPL = "VBQPPL"
    VNU = "VNU"
    UEB = "UEB"


class ReviewDecision(StrEnum):
    PASS = "PASS"
    REVISE = "REVISE"
    PARTIAL = "PARTIAL"
    BLOCK = "BLOCK"


def _private_text(value: str, *, maximum: int) -> str:
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError("private text must be nonblank and bounded")
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise ValueError("private text must not contain control characters")
    return normalized


class DocumentVersionReference(_FrozenLegalEvidenceModel):
    """Opaque deterministic document/version/provenance identity."""

    document_id: UUID = Field(exclude=True, repr=False)
    document_version_id: UUID = Field(exclude=True, repr=False)
    provenance_record_id: UUID = Field(exclude=True, repr=False)
    source_id: str = Field(min_length=1, max_length=32, exclude=True, repr=False)

    @field_validator("source_id")
    @classmethod
    def validate_source_id(cls, value: str) -> str:
        return _private_text(value, maximum=32)


class EvidenceReference(_FrozenLegalEvidenceModel):
    """A resolvable deterministic evidence locator with no retained source text."""

    reference_id: UUID = Field(default_factory=uuid4, exclude=True, repr=False)
    document: DocumentVersionReference = Field(exclude=True, repr=False)
    chunk_id: UUID = Field(exclude=True, repr=False)
    locator: str = Field(min_length=1, max_length=512, exclude=True, repr=False)

    @field_validator("locator")
    @classmethod
    def validate_locator(cls, value: str) -> str:
        return _private_text(value, maximum=512)


class QuestionAnalysis(_FrozenLegalEvidenceModel):
    """Request-local question analysis whose text never enters public diagnostics."""

    analysis_id: UUID = Field(default_factory=uuid4, exclude=True, repr=False)
    origin: AnalysisOrigin
    main_intent: str = Field(min_length=1, max_length=256, exclude=True, repr=False)
    ambiguous: bool = False
    legal_actor: str | None = Field(default=None, max_length=128, exclude=True, repr=False)
    legal_action_event: str | None = Field(default=None, max_length=128, exclude=True, repr=False)
    explicit_time: tuple[str, ...] = Field(default=(), max_length=4, exclude=True, repr=False)
    legal_topics: tuple[str, ...] = Field(default=(), max_length=4, exclude=True, repr=False)
    preferred_source_tiers: tuple[PreferredSourceTier, ...] = Field(
        default=(), max_length=3, exclude=True, repr=False
    )
    retrieval_concepts: tuple[str, ...] = Field(default=(), max_length=8, exclude=True, repr=False)

    @field_validator("main_intent")
    @classmethod
    def validate_main_intent(cls, value: str) -> str:
        return _private_text(value, maximum=256)

    @field_validator("legal_actor", "legal_action_event")
    @classmethod
    def validate_optional_private_values(cls, value: str | None) -> str | None:
        return None if value is None else _private_text(value, maximum=128)

    @field_validator("explicit_time", "legal_topics", "retrieval_concepts")
    @classmethod
    def validate_private_value_tuples(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("private analysis values must be unique")
        return tuple(_private_text(item, maximum=128) for item in value)

    @field_validator("preferred_source_tiers")
    @classmethod
    def validate_preferred_source_tiers(
        cls, value: tuple[PreferredSourceTier, ...]
    ) -> tuple[PreferredSourceTier, ...]:
        if len(set(value)) != len(value):
            raise ValueError("preferred source tiers must be unique")
        return value


class SubIntent(_FrozenLegalEvidenceModel):
    """One material legal issue, described only in private request state."""

    sub_intent_id: UUID = Field(default_factory=uuid4, exclude=True, repr=False)
    description: str = Field(min_length=1, max_length=512, exclude=True, repr=False)
    material: bool = True
    retrieval_concepts: tuple[str, ...] = Field(default=(), max_length=8, exclude=True, repr=False)
    preferred_source_tiers: tuple[PreferredSourceTier, ...] = Field(
        default=(), max_length=3, exclude=True, repr=False
    )

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        return _private_text(value, maximum=512)

    @field_validator("retrieval_concepts")
    @classmethod
    def validate_retrieval_concepts(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("sub-intent concepts must be unique")
        return tuple(_private_text(item, maximum=128) for item in value)

    @field_validator("preferred_source_tiers")
    @classmethod
    def validate_sub_intent_source_tiers(
        cls, value: tuple[PreferredSourceTier, ...]
    ) -> tuple[PreferredSourceTier, ...]:
        if len(set(value)) != len(value):
            raise ValueError("sub-intent source tiers must be unique")
        return value


class LegalQuestionAnalysisResult(_FrozenLegalEvidenceModel):
    """Bounded P2 output before it is applied to request state."""

    analysis: QuestionAnalysis = Field(exclude=True, repr=False)
    sub_intents: tuple[SubIntent, ...] = Field(
        min_length=1, max_length=_MAX_SUB_INTENTS, exclude=True, repr=False
    )
    outcome: AnalyzerOutcome

    @field_validator("sub_intents")
    @classmethod
    def validate_result_sub_intents(cls, value: tuple[SubIntent, ...]) -> tuple[SubIntent, ...]:
        if len({item.sub_intent_id for item in value}) != len(value):
            raise ValueError("analysis-result sub-intent identifiers must be unique")
        if any(not item.material for item in value):
            raise ValueError("analysis-result sub-intents must be material")
        return value

    def to_public_dict(self) -> dict[str, object]:
        return {
            "origin": self.analysis.origin.value,
            "outcome": self.outcome.value,
            "sub_intent_count": len(self.sub_intents),
            "ambiguous": self.analysis.ambiguous,
        }


class CandidateDocument(_FrozenLegalEvidenceModel):
    """A discovery candidate; its presence never establishes authority."""

    candidate_id: UUID = Field(default_factory=uuid4, exclude=True, repr=False)
    document: DocumentVersionReference = Field(exclude=True, repr=False)
    state: AuthorityState
    matched_sub_intent_ids: tuple[UUID, ...] = Field(default=(), max_length=_MAX_SUB_INTENTS)

    @field_validator("matched_sub_intent_ids")
    @classmethod
    def validate_matched_sub_intent_ids(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(set(value)) != len(value):
            raise ValueError("matched sub-intent identifiers must be unique")
        return value


class AuthorityCandidate(_FrozenLegalEvidenceModel):
    """A role proposal kept distinct from verified authority conclusions."""

    authority_candidate_id: UUID = Field(default_factory=uuid4, exclude=True, repr=False)
    document: DocumentVersionReference = Field(exclude=True, repr=False)
    role: AuthorityRole
    state: AuthorityState
    applicability: ApplicabilityState = ApplicabilityState.UNKNOWN
    proposal_only: bool = True

    @model_validator(mode="after")
    def validate_proposal_state(self) -> AuthorityCandidate:
        if self.proposal_only and self.applicability is ApplicabilityState.VERIFIED:
            raise ValueError("a proposal cannot assert verified applicability")
        if self.state is AuthorityState.QUARANTINED and self.role is AuthorityRole.GOVERNING:
            raise ValueError("quarantined evidence cannot be governing")
        return self


class AuthorityFamily(_FrozenLegalEvidenceModel):
    """A request-local group of evidence records without relation truth claims."""

    family_id: UUID = Field(default_factory=uuid4, exclude=True, repr=False)
    document_version_ids: tuple[UUID, ...] = Field(
        min_length=1, max_length=_MAX_CANDIDATES, exclude=True
    )

    @field_validator("document_version_ids")
    @classmethod
    def validate_document_version_ids(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(set(value)) != len(value):
            raise ValueError("authority-family document versions must be unique")
        return value


class RelationHint(_FrozenLegalEvidenceModel):
    """An LLM or heuristic hypothesis that cannot be treated as a legal fact."""

    relation_id: UUID = Field(default_factory=uuid4, exclude=True, repr=False)
    subject_document_version_id: UUID = Field(exclude=True, repr=False)
    object_document_version_id: UUID = Field(exclude=True, repr=False)
    relation_type: RelationType
    verification: RelationVerification = RelationVerification.HINT_ONLY
    proposal_only: bool = True

    @model_validator(mode="after")
    def validate_hint_only(self) -> RelationHint:
        if self.subject_document_version_id == self.object_document_version_id:
            raise ValueError("relation endpoints must differ")
        if self.verification is not RelationVerification.HINT_ONLY or not self.proposal_only:
            raise ValueError("relation hints must remain proposal-only")
        return self


class VerifiedRelation(_FrozenLegalEvidenceModel):
    """A relation usable only with a deterministic, resolvable evidence reference."""

    relation_id: UUID = Field(default_factory=uuid4, exclude=True, repr=False)
    subject_document_version_id: UUID = Field(exclude=True, repr=False)
    object_document_version_id: UUID = Field(exclude=True, repr=False)
    relation_type: RelationType
    verification: RelationVerification
    evidence: EvidenceReference = Field(exclude=True, repr=False)
    reviewed_by: str | None = Field(default=None, max_length=128, exclude=True, repr=False)

    @field_validator("reviewed_by")
    @classmethod
    def validate_reviewed_by(cls, value: str | None) -> str | None:
        return None if value is None else _private_text(value, maximum=128)

    @model_validator(mode="after")
    def validate_verified_relation(self) -> VerifiedRelation:
        if self.subject_document_version_id == self.object_document_version_id:
            raise ValueError("relation endpoints must differ")
        if self.verification not in (
            RelationVerification.EVIDENCE_VERIFIED,
            RelationVerification.REVIEWED,
        ):
            raise ValueError("verified relations require evidence-verified state")
        if self.verification is RelationVerification.REVIEWED and self.reviewed_by is None:
            raise ValueError("reviewed relations require an opaque reviewer identifier")
        if (
            self.verification is RelationVerification.EVIDENCE_VERIFIED
            and self.reviewed_by is not None
        ):
            raise ValueError("evidence-verified relations cannot include a reviewer")
        return self


class EvidenceUnit(_FrozenLegalEvidenceModel):
    """Pinpoint evidence contract for a later reader phase."""

    evidence_unit_id: UUID = Field(default_factory=uuid4, exclude=True, repr=False)
    evidence: EvidenceReference = Field(exclude=True, repr=False)
    supported_sub_intent_ids: tuple[UUID, ...] = Field(
        min_length=1, max_length=_MAX_SUB_INTENTS, exclude=True, repr=False
    )
    authority_role: AuthorityRole

    @field_validator("supported_sub_intent_ids")
    @classmethod
    def validate_supported_sub_intent_ids(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(set(value)) != len(value):
            raise ValueError("supported sub-intent identifiers must be unique")
        return value


class CoverageEntry(_FrozenLegalEvidenceModel):
    """Coverage outcome for exactly one material sub-intent."""

    sub_intent_id: UUID = Field(exclude=True, repr=False)
    state: CoverageState
    governing_authority_present: bool
    applicability: ApplicabilityState = ApplicabilityState.UNKNOWN


class CoverageMatrix(_FrozenLegalEvidenceModel):
    """Immutable per-sub-intent coverage matrix."""

    entries: tuple[CoverageEntry, ...] = Field(min_length=1, max_length=_MAX_SUB_INTENTS)

    @field_validator("entries")
    @classmethod
    def validate_entries(cls, value: tuple[CoverageEntry, ...]) -> tuple[CoverageEntry, ...]:
        if len({entry.sub_intent_id for entry in value}) != len(value):
            raise ValueError("coverage entries must be unique per sub-intent")
        return value


class AnswerDraft(_FrozenLegalEvidenceModel):
    """Private draft content that has not yet passed review."""

    draft_id: UUID = Field(default_factory=uuid4, exclude=True, repr=False)
    text: str = Field(min_length=1, max_length=20_000, exclude=True, repr=False)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _private_text(value, maximum=20_000)


class ReviewResult(_FrozenLegalEvidenceModel):
    """Request-local review result without raw reviewer text."""

    decision: ReviewDecision
    finding_codes: tuple[str, ...] = Field(default=(), max_length=20)
    rewrite_count: int = Field(default=0, ge=0, le=1)

    @field_validator("finding_codes")
    @classmethod
    def validate_finding_codes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("review finding codes must be unique")
        return tuple(_private_text(code, maximum=64) for code in value)


class LegalCaseContext(_FrozenLegalEvidenceModel):
    """Immutable request-level state for the sequential legal-evidence pipeline."""

    case_id: UUID = Field(default_factory=uuid4, exclude=True, repr=False)
    question_text: str = Field(min_length=1, max_length=4_000, exclude=True, repr=False)
    organization_context: str | None = Field(default=None, max_length=512, exclude=True, repr=False)
    conversation_summary: str | None = Field(
        default=None, max_length=2_000, exclude=True, repr=False
    )
    stage: CaseStage = CaseStage.RECEIVED
    question_analysis: QuestionAnalysis | None = Field(default=None, exclude=True, repr=False)
    sub_intents: tuple[SubIntent, ...] = Field(
        default=(), max_length=_MAX_SUB_INTENTS, exclude=True
    )
    candidate_documents: tuple[CandidateDocument, ...] = Field(
        default=(), max_length=_MAX_CANDIDATES, exclude=True
    )
    authority_candidates: tuple[AuthorityCandidate, ...] = Field(
        default=(), max_length=_MAX_CANDIDATES, exclude=True
    )
    authority_families: tuple[AuthorityFamily, ...] = Field(
        default=(), max_length=_MAX_FAMILIES, exclude=True
    )
    relation_hints: tuple[RelationHint, ...] = Field(
        default=(), max_length=_MAX_RELATIONS, exclude=True
    )
    verified_relations: tuple[VerifiedRelation, ...] = Field(
        default=(), max_length=_MAX_RELATIONS, exclude=True
    )
    evidence_units: tuple[EvidenceUnit, ...] = Field(
        default=(), max_length=_MAX_EVIDENCE_UNITS, exclude=True
    )
    coverage_matrix: CoverageMatrix | None = Field(default=None, exclude=True, repr=False)
    limitations: tuple[str, ...] = Field(default=(), max_length=20)
    answer_draft: AnswerDraft | None = Field(default=None, exclude=True, repr=False)
    review_result: ReviewResult | None = Field(default=None, exclude=True, repr=False)
    repair_count: int = Field(default=0, ge=0, le=1)

    @field_validator("question_text")
    @classmethod
    def validate_question_text(cls, value: str) -> str:
        return _private_text(value, maximum=4_000)

    @field_validator("organization_context", "conversation_summary")
    @classmethod
    def validate_optional_context(cls, value: str | None) -> str | None:
        maximum = 512 if value is not None and len(value) <= 512 else 2_000
        return None if value is None else _private_text(value, maximum=maximum)

    @field_validator("sub_intents")
    @classmethod
    def validate_sub_intents(cls, value: tuple[SubIntent, ...]) -> tuple[SubIntent, ...]:
        if len({item.sub_intent_id for item in value}) != len(value):
            raise ValueError("sub-intent identifiers must be unique")
        if any(not item.material for item in value):
            raise ValueError("case context can contain only material sub-intents")
        return value

    @field_validator("limitations")
    @classmethod
    def validate_limitations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("limitation codes must be unique")
        return tuple(_private_text(code, maximum=64) for code in value)

    @model_validator(mode="after")
    def validate_stage_requirements(self) -> LegalCaseContext:
        if self.stage is not CaseStage.RECEIVED and self.question_analysis is None:
            raise ValueError("advanced case stages require question analysis")
        if self.stage is not CaseStage.RECEIVED and not self.sub_intents:
            raise ValueError("advanced case stages require material sub-intents")
        if (
            self.stage
            in (
                CaseStage.COVERAGE_REVIEWED,
                CaseStage.REPAIRED,
                CaseStage.EVIDENCE_SELECTED,
                CaseStage.ANSWER_DRAFTED,
                CaseStage.ANSWER_REVIEWED,
            )
            and self.coverage_matrix is None
        ):
            raise ValueError("coverage stages require a coverage matrix")
        if (
            self.stage in (CaseStage.ANSWER_DRAFTED, CaseStage.ANSWER_REVIEWED)
            and self.answer_draft is None
        ):
            raise ValueError("answer stages require an answer draft")
        if self.stage is CaseStage.ANSWER_REVIEWED and self.review_result is None:
            raise ValueError("reviewed cases require a review result")
        return self

    def to_public_dict(self) -> dict[str, object]:
        """Return only aggregate, non-content diagnostics safe for ordinary logs."""

        return {
            "stage": self.stage.value,
            "sub_intent_count": len(self.sub_intents),
            "candidate_document_count": len(self.candidate_documents),
            "authority_candidate_count": len(self.authority_candidates),
            "authority_family_count": len(self.authority_families),
            "relation_hint_count": len(self.relation_hints),
            "verified_relation_count": len(self.verified_relations),
            "evidence_unit_count": len(self.evidence_units),
            "coverage_entry_count": (
                0 if self.coverage_matrix is None else len(self.coverage_matrix.entries)
            ),
            "limitation_count": len(self.limitations),
            "has_answer_draft": self.answer_draft is not None,
            "review_decision": None
            if self.review_result is None
            else self.review_result.decision.value,
            "repair_count": self.repair_count,
        }


__all__ = [
    "AnalysisOrigin",
    "AnalyzerOutcome",
    "AnswerDraft",
    "ApplicabilityState",
    "AuthorityCandidate",
    "AuthorityFamily",
    "AuthorityRole",
    "AuthorityState",
    "CandidateDocument",
    "CaseStage",
    "CoverageEntry",
    "CoverageMatrix",
    "CoverageState",
    "DocumentVersionReference",
    "EvidenceReference",
    "EvidenceUnit",
    "LegalCaseContext",
    "LegalQuestionAnalysisResult",
    "LegalTruthCategory",
    "QuestionAnalysis",
    "PreferredSourceTier",
    "RelationHint",
    "RelationType",
    "RelationVerification",
    "ReviewDecision",
    "ReviewResult",
    "SubIntent",
    "VerifiedRelation",
]
