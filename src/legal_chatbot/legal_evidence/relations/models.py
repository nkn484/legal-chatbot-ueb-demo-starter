"""P5 relation hint and evidence-backed family contracts."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from legal_chatbot.legal_evidence.models import (
    AuthorityCandidate,
    AuthorityFamily,
    EvidenceReference,
    RelationHint,
    RelationType,
    VerifiedRelation,
)


class _FrozenRelationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RelationInvestigationOutcome(StrEnum):
    DISABLED_FALLBACK = "DISABLED_FALLBACK"
    LLM_HINTS = "LLM_HINTS"
    INVALID_OUTPUT_FALLBACK = "INVALID_OUTPUT_FALLBACK"
    PROVIDER_FAILURE_FALLBACK = "PROVIDER_FAILURE_FALLBACK"


class RelationEvidenceMarker(StrEnum):
    AMENDS = "AMENDS"
    REPLACES = "REPLACES"
    REPEALS = "REPEALS"
    IMPLEMENTS = "IMPLEMENTS"
    GOVERNS = "GOVERNS"


class RelationInvestigationSettings(_FrozenRelationModel):
    enabled: bool = False
    max_output_tokens: int = Field(default=512, ge=64, le=1024)
    timeout_seconds: float = Field(default=15.0, gt=0, le=30)


class RelationHintProposal(_FrozenRelationModel):
    subject_index: int = Field(ge=0, le=29)
    object_index: int = Field(ge=0, le=29)
    relation_type: RelationType


class RelationEvidence(_FrozenRelationModel):
    hint_id: UUID = Field(exclude=True, repr=False)
    marker: RelationEvidenceMarker
    evidence: EvidenceReference = Field(exclude=True, repr=False)


class RelationConflict(_FrozenRelationModel):
    subject_document_version_id: UUID = Field(exclude=True, repr=False)
    object_document_version_id: UUID = Field(exclude=True, repr=False)
    relation_types: tuple[RelationType, ...]


class RelationInvestigationResult(_FrozenRelationModel):
    families: tuple[AuthorityFamily, ...] = Field(default=(), max_length=15, exclude=True)
    hints: tuple[RelationHint, ...] = Field(default=(), max_length=30, exclude=True)
    verified: tuple[VerifiedRelation, ...] = Field(default=(), max_length=30, exclude=True)
    conflicts: tuple[RelationConflict, ...] = Field(default=(), max_length=30)
    retained_document_version_ids: tuple[UUID, ...] = Field(default=(), max_length=15, exclude=True)
    budget_pruned_document_version_ids: tuple[UUID, ...] = Field(
        default=(), max_length=30, exclude=True
    )
    outcome: RelationInvestigationOutcome

    def to_public_dict(self) -> dict[str, object]:
        return {
            "outcome": self.outcome.value,
            "family_count": len(self.families),
            "hint_count": len(self.hints),
            "verified_count": len(self.verified),
            "conflict_count": len(self.conflicts),
            "retained_document_count": len(self.retained_document_version_ids),
            "budget_pruned_document_count": len(self.budget_pruned_document_version_ids),
        }


def marker_matches(marker: RelationEvidenceMarker, relation_type: RelationType) -> bool:
    return marker.value == relation_type.value


def build_families(
    candidates: tuple[AuthorityCandidate, ...], verified: tuple[VerifiedRelation, ...]
) -> tuple[AuthorityFamily, ...]:
    parent = {
        candidate.document.document_version_id: candidate.document.document_version_id
        for candidate in candidates
    }

    # Stable document identity is deterministic evidence for a multi-version family.
    first_version_by_document: dict[UUID, UUID] = {}
    for candidate in candidates:
        version_id = candidate.document.document_version_id
        document_id = candidate.document.document_id
        first = first_version_by_document.setdefault(document_id, version_id)
        parent[version_id] = first

    def find(value: UUID) -> UUID:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    for relation in verified:
        if (
            relation.subject_document_version_id in parent
            and relation.object_document_version_id in parent
        ):
            parent[find(relation.object_document_version_id)] = find(
                relation.subject_document_version_id
            )
    groups: dict[UUID, list[UUID]] = {}
    for version_id in parent:
        groups.setdefault(find(version_id), []).append(version_id)
    return tuple(
        AuthorityFamily(document_version_ids=tuple(sorted(version_ids)))
        for _, version_ids in sorted(groups.items(), key=lambda item: str(item[0]))
    )


__all__ = [
    "RelationConflict",
    "RelationEvidence",
    "RelationEvidenceMarker",
    "RelationHintProposal",
    "RelationInvestigationOutcome",
    "RelationInvestigationResult",
    "RelationInvestigationSettings",
    "build_families",
    "marker_matches",
]
