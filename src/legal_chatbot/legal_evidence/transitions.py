"""Deterministic transitions for legal-case state and verified legal relations."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from .models import (
    ApplicabilityState,
    CaseStage,
    EvidenceReference,
    LegalCaseContext,
    RelationHint,
    RelationVerification,
    VerifiedRelation,
)


class LegalCaseTransitionError(ValueError):
    """Raised when request state would skip, regress, or bypass a required stage."""


_STAGE_ORDER = (
    CaseStage.RECEIVED,
    CaseStage.ANALYZED,
    CaseStage.DISCOVERED,
    CaseStage.AUTHORITY_REVIEWED,
    CaseStage.FAMILIES_RESOLVED,
    CaseStage.EVIDENCE_READ,
    CaseStage.COVERAGE_REVIEWED,
    CaseStage.REPAIRED,
    CaseStage.EVIDENCE_SELECTED,
    CaseStage.ANSWER_DRAFTED,
    CaseStage.ANSWER_REVIEWED,
)
_UPDATABLE_FIELDS = frozenset(LegalCaseContext.model_fields) - {
    "case_id",
    "question_text",
    "stage",
}


def advance_case(
    context: LegalCaseContext, target_stage: CaseStage, /, **updates: Any
) -> LegalCaseContext:
    """Advance exactly one stage while preserving private request-local fields."""

    try:
        current_index = _STAGE_ORDER.index(context.stage)
        target_index = _STAGE_ORDER.index(target_stage)
    except ValueError as error:
        raise LegalCaseTransitionError("unknown legal-case stage") from error
    if target_index != current_index + 1:
        raise LegalCaseTransitionError("legal-case transitions must advance exactly one stage")
    unexpected = set(updates) - _UPDATABLE_FIELDS
    if unexpected:
        raise LegalCaseTransitionError("legal-case transition includes immutable field updates")
    values = {name: getattr(context, name) for name in LegalCaseContext.model_fields}
    values.update(updates)
    values["stage"] = target_stage
    return LegalCaseContext(**values)


def verify_relation(
    hint: RelationHint,
    evidence: EvidenceReference,
    *,
    relation_id: UUID | None = None,
) -> VerifiedRelation:
    """Promote a hint only through a supplied, resolvable evidence reference."""

    return VerifiedRelation(
        relation_id=hint.relation_id if relation_id is None else relation_id,
        subject_document_version_id=hint.subject_document_version_id,
        object_document_version_id=hint.object_document_version_id,
        relation_type=hint.relation_type,
        verification=RelationVerification.EVIDENCE_VERIFIED,
        evidence=evidence,
    )


def record_reviewed_relation(
    verified_relation: VerifiedRelation, *, reviewed_by: str
) -> VerifiedRelation:
    """Record an opaque human-review identifier without changing evidence identity."""

    if verified_relation.verification is not RelationVerification.EVIDENCE_VERIFIED:
        raise LegalCaseTransitionError("only evidence-verified relations can be reviewed")
    return VerifiedRelation(
        relation_id=verified_relation.relation_id,
        subject_document_version_id=verified_relation.subject_document_version_id,
        object_document_version_id=verified_relation.object_document_version_id,
        relation_type=verified_relation.relation_type,
        verification=RelationVerification.REVIEWED,
        evidence=verified_relation.evidence,
        reviewed_by=reviewed_by,
    )


def verified_applicability_state(evidence: tuple[EvidenceReference, ...]) -> ApplicabilityState:
    """Allow verified applicability only when deterministic evidence is supplied."""

    if not evidence:
        raise LegalCaseTransitionError("verified applicability requires evidence")
    if len({item.reference_id for item in evidence}) != len(evidence):
        raise LegalCaseTransitionError("verified applicability evidence must be unique")
    return ApplicabilityState.VERIFIED


__all__ = [
    "LegalCaseTransitionError",
    "advance_case",
    "record_reviewed_relation",
    "verified_applicability_state",
    "verify_relation",
]
