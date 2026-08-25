"""P4 authority proposals and deterministic validation contracts."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from legal_chatbot.legal_evidence.models import (
    ApplicabilityState,
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


class AuthorityReviewSettings(_FrozenAuthorityModel):
    enabled: bool = False
    max_output_tokens: int = Field(default=512, ge=64, le=1_024)
    timeout_seconds: float = Field(default=15.0, gt=0, le=30)


class AuthorityMetadata(_FrozenAuthorityModel):
    """Deterministic ingestion metadata; it makes no legal-effect conclusion."""

    document: DocumentVersionReference = Field(exclude=True, repr=False)
    discovery_state: AuthorityState
    provenance_valid: bool
    scope_compatible: bool
    source_binding_compatible: bool
    status_eligible: bool
    status_metadata_current: bool = False


class AuthorityRoleProposal(_FrozenAuthorityModel):
    candidate_index: int = Field(ge=0, le=29)
    role: AuthorityRole


class AuthorityReviewResult(_FrozenAuthorityModel):
    candidates: tuple[AuthorityCandidate, ...] = Field(default=(), max_length=30, exclude=True)
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
        return {"outcome": self.outcome.value, "state_counts": states, "role_counts": roles}


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
        )
    if not metadata.provenance_valid:
        return AuthorityCandidate(
            document=metadata.document,
            role=AuthorityRole.IRRELEVANT,
            state=AuthorityState.FILTERED_PROVENANCE,
            applicability=ApplicabilityState.UNKNOWN,
            proposal_only=proposal_only,
        )
    if not metadata.scope_compatible:
        return AuthorityCandidate(
            document=metadata.document,
            role=AuthorityRole.IRRELEVANT,
            state=AuthorityState.FILTERED_SCOPE,
            applicability=ApplicabilityState.UNKNOWN,
            proposal_only=proposal_only,
        )
    if not metadata.source_binding_compatible:
        return AuthorityCandidate(
            document=metadata.document,
            role=AuthorityRole.IRRELEVANT,
            state=AuthorityState.FILTERED_SOURCE_BINDING,
            applicability=ApplicabilityState.UNKNOWN,
            proposal_only=proposal_only,
        )
    if not metadata.status_eligible:
        return AuthorityCandidate(
            document=metadata.document,
            role=AuthorityRole.IRRELEVANT,
            state=AuthorityState.FILTERED_STATUS,
            applicability=ApplicabilityState.UNKNOWN,
            proposal_only=proposal_only,
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
    )


__all__ = [
    "AuthorityMetadata",
    "AuthorityReviewOutcome",
    "AuthorityReviewResult",
    "AuthorityReviewSettings",
    "AuthorityRoleProposal",
    "validate_authority_candidate",
]
