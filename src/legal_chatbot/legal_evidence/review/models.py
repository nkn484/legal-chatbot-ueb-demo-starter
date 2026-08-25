"""P11 review contracts for an evidence-bound legal answer draft."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from legal_chatbot.legal_evidence.composition.models import CompositionEvidence, CompositionResult
from legal_chatbot.legal_evidence.models import ReviewDecision


class _FrozenReviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReviewFindingCode(StrEnum):
    UNSUPPORTED_MATERIAL_CLAIM = "UNSUPPORTED_MATERIAL_CLAIM"
    AUTHORITY_ROLE_CONFUSION = "AUTHORITY_ROLE_CONFUSION"
    APPLICABILITY_OVERSTATED = "APPLICABILITY_OVERSTATED"
    MATERIAL_SUBINTENT_OMITTED = "MATERIAL_SUBINTENT_OMITTED"
    UNRESOLVED_ISSUE_NOT_QUALIFIED = "UNRESOLVED_ISSUE_NOT_QUALIFIED"
    LEGAL_EFFECT_UNSUPPORTED = "LEGAL_EFFECT_UNSUPPORTED"
    CLAIM_REFERENCE_INVALID = "CLAIM_REFERENCE_INVALID"
    EVIDENCE_REFERENCE_INVALID = "EVIDENCE_REFERENCE_INVALID"
    COMPOSITION_DRAFT_MISMATCH = "COMPOSITION_DRAFT_MISMATCH"
    EVIDENCE_PACK_DRIFT = "EVIDENCE_PACK_DRIFT"
    REVIEWER_OUTPUT_INVALID = "REVIEWER_OUTPUT_INVALID"
    REVIEWER_UNAVAILABLE = "REVIEWER_UNAVAILABLE"
    REWRITE_UNAVAILABLE = "REWRITE_UNAVAILABLE"
    REWRITE_INVALID = "REWRITE_INVALID"
    REWRITE_EXHAUSTED = "REWRITE_EXHAUSTED"


class ReviewerExecutionOutcome(StrEnum):
    DISABLED = "DISABLED"
    REVIEWED = "REVIEWED"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    REWRITE_FAILURE = "REWRITE_FAILURE"


class P11GuardOutcome(StrEnum):
    P12_CANDIDATE_ONLY = "P12_CANDIDATE_ONLY"
    PARTIAL_NOT_RELEASABLE = "PARTIAL_NOT_RELEASABLE"
    BLOCKED_NOT_RELEASABLE = "BLOCKED_NOT_RELEASABLE"
    DISABLED_NOT_RELEASABLE = "DISABLED_NOT_RELEASABLE"


class ReviewSettings(_FrozenReviewModel):
    """Default-off bounded settings for the independent P11 reviewer."""

    enabled: bool = False
    max_output_tokens: int = Field(default=512, ge=64, le=1024)
    timeout_seconds: float = Field(default=20.0, gt=0, le=30)
    rewrite_max_output_tokens: int = Field(default=768, ge=64, le=1024)
    max_rewrites: int = Field(default=1, ge=0, le=1)
    max_reviewer_passes: int = Field(default=2, ge=1, le=2)


class ReviewFinding(_FrozenReviewModel):
    """A reviewer finding expressed only through existing pack indices and codes."""

    code: ReviewFindingCode
    claim_indices: tuple[int, ...] = Field(default=(), max_length=50)
    sub_intent_indices: tuple[int, ...] = Field(default=(), max_length=4)
    evidence_indices: tuple[int, ...] = Field(default=(), max_length=6)

    @field_validator("claim_indices", "sub_intent_indices", "evidence_indices")
    @classmethod
    def validate_indices(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if any(index < 0 for index in value) or len(set(value)) != len(value):
            raise ValueError("review indices must be unique non-negative values")
        return value


class ReviewProposal(_FrozenReviewModel):
    """Strict provider proposal; it cannot carry free-text law or evidence identifiers."""

    decision: ReviewDecision
    findings: tuple[ReviewFinding, ...] = Field(default=(), max_length=20, exclude=True)

    @model_validator(mode="after")
    def validate_decision_findings(self) -> "ReviewProposal":
        if self.decision is ReviewDecision.PASS and self.findings:
            raise ValueError("pass proposal cannot contain findings")
        if self.decision is not ReviewDecision.PASS and not self.findings:
            raise ValueError("non-pass proposal requires a finding")
        return self


class P11ReviewResult(_FrozenReviewModel):
    """Private P11 result with a public count-only operational projection."""

    decision: ReviewDecision | None = None
    findings: tuple[ReviewFinding, ...] = Field(default=(), max_length=40, exclude=True)
    reviewer_execution: ReviewerExecutionOutcome
    reviewer_pass_count: int = Field(ge=0, le=2)
    rewrite_count: int = Field(ge=0, le=1)
    guard_outcome: P11GuardOutcome
    evidence_identity_preserved: bool

    def to_public_dict(self) -> dict[str, object]:
        code_counts = {code.value: 0 for code in ReviewFindingCode}
        for finding in self.findings:
            code_counts[finding.code.value] += 1
        return {
            "decision": None if self.decision is None else self.decision.value,
            "reviewer_execution": self.reviewer_execution.value,
            "reviewer_pass_count": self.reviewer_pass_count,
            "rewrite_count": self.rewrite_count,
            "guard_outcome": self.guard_outcome.value,
            "evidence_identity_preserved": self.evidence_identity_preserved,
            "finding_counts": {key: value for key, value in code_counts.items() if value},
        }


class P11ReviewContextResult(_FrozenReviewModel):
    """Return the reviewed context without serializing its private legal text."""

    context: object = Field(exclude=True, repr=False)
    result: P11ReviewResult
    composition: CompositionResult = Field(exclude=True, repr=False)


class ReviewEvidencePack(_FrozenReviewModel):
    """Exact selected evidence passed from P10 to the reviewer or one rewrite."""

    evidence: tuple[CompositionEvidence, ...] = Field(default=(), max_length=6, exclude=True)


__all__ = [
    "P11GuardOutcome",
    "P11ReviewContextResult",
    "P11ReviewResult",
    "ReviewEvidencePack",
    "ReviewFinding",
    "ReviewFindingCode",
    "ReviewProposal",
    "ReviewSettings",
    "ReviewerExecutionOutcome",
]
