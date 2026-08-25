"""P4 authority proposals and deterministic validation contracts."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from legal_chatbot.legal_evidence.models import (
    ApplicabilityState,
    AuthorityAssessment,
    AuthorityCandidate,
    AuthorityRole,
    AuthorityState,
    DocumentVersionReference,
)


class _FrozenAuthorityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AuthorityReviewOutcome(StrEnum):
    DISABLED_FALLBACK = "DISABLED_FALLBACK"
    LLM_PROPOSALS = "LLM_PROPOSALS"
    INVALID_OUTPUT_FALLBACK = "INVALID_OUTPUT_FALLBACK"
    PROVIDER_FAILURE_FALLBACK = "PROVIDER_FAILURE_FALLBACK"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_CONNECTION_FAILURE = "PROVIDER_CONNECTION_FAILURE"
    INVALID_STRUCTURED_OUTPUT = "INVALID_STRUCTURED_OUTPUT"
    OUTPUT_TRUNCATED = "OUTPUT_TRUNCATED"
    PROVIDER_RATE_LIMIT = "PROVIDER_RATE_LIMIT"
    PROVIDER_SERVER_ERROR = "PROVIDER_SERVER_ERROR"
    BATCH_PARTIAL_FAILURE = "BATCH_PARTIAL_FAILURE"
    UNKNOWN_PROVIDER_FAILURE = "UNKNOWN_PROVIDER_FAILURE"
    PROVIDER_SUPPRESSED = "PROVIDER_SUPPRESSED"


class AuthorityReviewSettings(_FrozenAuthorityModel):
    enabled: bool = False
    max_output_tokens: int = Field(default=1_024, ge=64, le=1_024)
    timeout_seconds: float = Field(default=15.0, gt=0, le=30)
    batch_size: int = Field(default=8, ge=1, le=10)
    batch_concurrency: int = Field(default=1, ge=1, le=3)
    batch_max_attempts: int = Field(default=2, ge=1, le=2)


class AuthorityMetadata(_FrozenAuthorityModel):
    """Deterministic ingestion metadata; it makes no legal-effect conclusion."""

    document: DocumentVersionReference = Field(exclude=True, repr=False)
    discovery_state: AuthorityState
    provenance_valid: bool
    scope_compatible: bool
    source_binding_compatible: bool
    status_eligible: bool
    status_metadata_current: bool = False
    matched_sub_intent_ids: tuple[UUID, ...] = Field(default=(), max_length=4, exclude=True)
    scope_conflict: bool = False
    catalog_state: AuthorityState = AuthorityState.ELIGIBLE
    title: str | None = Field(default=None, max_length=4_096, exclude=True, repr=False)
    document_type: str | None = Field(default=None, max_length=512, exclude=True, repr=False)
    issuing_authority: str | None = Field(default=None, max_length=1_024, exclude=True, repr=False)


class AuthorityRoleProposal(_FrozenAuthorityModel):
    candidate_index: int = Field(ge=0, le=29)
    role: AuthorityRole


class AuthorityAssessmentProposal(_FrozenAuthorityModel):
    candidate_index: int = Field(ge=0, le=29)
    sub_intent_index: int = Field(ge=0, le=3)
    role: AuthorityRole


class AuthorityReviewResult(_FrozenAuthorityModel):
    candidates: tuple[AuthorityCandidate, ...] = Field(default=(), max_length=30, exclude=True)
    assessments: tuple[AuthorityAssessment, ...] = Field(default=(), max_length=120, exclude=True)
    llm_assessment_count: int = Field(default=0, ge=0, le=120)
    fallback_assessment_count: int = Field(default=0, ge=0, le=120)
    outcome: AuthorityReviewOutcome

    @field_validator("candidates")
    @classmethod
    def validate_unique(
        cls, value: tuple[AuthorityCandidate, ...]
    ) -> tuple[AuthorityCandidate, ...]:
        identifiers = [candidate.document.document_version_id for candidate in value]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("authority candidates must be unique by document version")
        return value

    def to_public_dict(self) -> dict[str, object]:
        states = {state.value: 0 for state in AuthorityState}
        roles = {role.value: 0 for role in AuthorityRole}
        for candidate in self.candidates:
            states[candidate.state.value] += 1
            roles[candidate.role.value] += 1
        assessment_roles = {role.value: 0 for role in AuthorityRole}
        for assessment in self.assessments:
            assessment_roles[assessment.role.value] += 1
        return {
            "outcome": self.outcome.value,
            "state_counts": states,
            "role_counts": roles,
            "assessment_role_counts": assessment_roles,
            "llm_assessment_count": self.llm_assessment_count,
            "fallback_assessment_count": self.fallback_assessment_count,
        }


def validate_authority_candidate(
    metadata: AuthorityMetadata,
    proposal_role: AuthorityRole,
    *,
    proposal_only: bool,
) -> AuthorityCandidate:
    """Apply hard filters before accepting a role proposal or soft qualification."""

    if metadata.discovery_state is not AuthorityState.ELIGIBLE:
        return AuthorityCandidate(
            document=metadata.document,
            role=AuthorityRole.IRRELEVANT,
            state=metadata.discovery_state,
            applicability=ApplicabilityState.UNKNOWN,
            proposal_only=proposal_only,
            matched_sub_intent_ids=metadata.matched_sub_intent_ids,
            filter_reason=metadata.discovery_state,
            scope_conflict=metadata.scope_conflict,
            catalog_state=metadata.catalog_state,
        )
    if not metadata.provenance_valid:
        return AuthorityCandidate(
            document=metadata.document,
            role=AuthorityRole.IRRELEVANT,
            state=AuthorityState.FILTERED_PROVENANCE,
            applicability=ApplicabilityState.UNKNOWN,
            proposal_only=proposal_only,
            matched_sub_intent_ids=metadata.matched_sub_intent_ids,
            filter_reason=AuthorityState.FILTERED_PROVENANCE,
            scope_conflict=metadata.scope_conflict,
            catalog_state=metadata.catalog_state,
        )
    if not metadata.scope_compatible:
        return AuthorityCandidate(
            document=metadata.document,
            role=AuthorityRole.IRRELEVANT,
            state=AuthorityState.FILTERED_SCOPE,
            applicability=ApplicabilityState.UNKNOWN,
            proposal_only=proposal_only,
            matched_sub_intent_ids=metadata.matched_sub_intent_ids,
            filter_reason=AuthorityState.FILTERED_SCOPE,
            scope_conflict=True,
            catalog_state=metadata.catalog_state,
        )
    if not metadata.source_binding_compatible:
        return AuthorityCandidate(
            document=metadata.document,
            role=AuthorityRole.IRRELEVANT,
            state=AuthorityState.FILTERED_SOURCE_BINDING,
            applicability=ApplicabilityState.UNKNOWN,
            proposal_only=proposal_only,
            matched_sub_intent_ids=metadata.matched_sub_intent_ids,
            filter_reason=AuthorityState.FILTERED_SOURCE_BINDING,
            scope_conflict=metadata.scope_conflict,
            catalog_state=metadata.catalog_state,
        )
    if not metadata.status_eligible:
        return AuthorityCandidate(
            document=metadata.document,
            role=AuthorityRole.IRRELEVANT,
            state=AuthorityState.FILTERED_STATUS,
            applicability=ApplicabilityState.UNKNOWN,
            proposal_only=proposal_only,
            matched_sub_intent_ids=metadata.matched_sub_intent_ids,
            filter_reason=AuthorityState.FILTERED_STATUS,
            scope_conflict=metadata.scope_conflict,
            catalog_state=metadata.catalog_state,
        )
    return AuthorityCandidate(
        document=metadata.document,
        role=proposal_role,
        state=AuthorityState.ELIGIBLE,
        applicability=(
            ApplicabilityState.METADATA_CURRENT
            if metadata.status_metadata_current
            else ApplicabilityState.CURRENT_EFFECT_UNVERIFIED
        ),
        proposal_only=proposal_only,
        matched_sub_intent_ids=metadata.matched_sub_intent_ids,
        scope_conflict=metadata.scope_conflict,
        catalog_state=metadata.catalog_state,
    )


def validate_authority_assessment(
    metadata: AuthorityMetadata,
    sub_intent_id: UUID,
    proposal_role: AuthorityRole,
    *,
    proposal_only: bool,
) -> AuthorityAssessment:
    """Apply P4 hard filters independently for every material sub-intent."""

    candidate = validate_authority_candidate(
        metadata, proposal_role, proposal_only=proposal_only
    )
    return AuthorityAssessment(
        document=metadata.document,
        sub_intent_id=sub_intent_id,
        proposed_role=proposal_role,
        role=candidate.role,
        state=candidate.state,
        applicability=candidate.applicability,
        proposal_only=proposal_only,
        scope_conflict=candidate.scope_conflict,
        filter_reason=candidate.filter_reason,
    )


__all__ = [
    "AuthorityMetadata",
    "AuthorityAssessmentProposal",
    "AuthorityReviewOutcome",
    "AuthorityReviewResult",
    "AuthorityReviewSettings",
    "AuthorityRoleProposal",
    "validate_authority_candidate",
    "validate_authority_assessment",
]
