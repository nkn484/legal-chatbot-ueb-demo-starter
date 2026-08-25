"""Coverage-preserving, bounded evidence selection."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from .analyzer import AnalyzerObservation
from .candidate_roles import AuthorityRole, CandidateRoleAssessment, assess_candidate_role
from .models import CollapsedDocumentCandidate, _FrozenContract

_MIN_EVIDENCE = 3
_MAX_DYNAMIC_EVIDENCE = 6


class EvidenceSelection(_FrozenContract):
    """Private selected candidates with content-free public selection diagnostics."""

    candidates: tuple[CollapsedDocumentCandidate, ...] = Field(
        default=(), max_length=_MAX_DYNAMIC_EVIDENCE, exclude=True, repr=False
    )
    assessments: tuple[CandidateRoleAssessment, ...] = Field(default=(), max_length=6)
    target_count: int = Field(ge=_MIN_EVIDENCE, le=_MAX_DYNAMIC_EVIDENCE)
    dynamic: bool

    @field_validator("assessments")
    @classmethod
    def validate_assessments(
        cls, value: tuple[CandidateRoleAssessment, ...]
    ) -> tuple[CandidateRoleAssessment, ...]:
        if len({item.document_version_id for item in value}) != len(value):
            raise ValueError("assessments must be unique per document version")
        return value

    @model_validator(mode="after")
    def validate_selection(self) -> EvidenceSelection:
        candidate_ids = tuple(
            candidate.identity.document_version_id for candidate in self.candidates
        )
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("selected evidence must be unique per document version")
        if candidate_ids != tuple(item.document_version_id for item in self.assessments):
            raise ValueError("assessments must match selected evidence order")
        if len(self.candidates) > self.target_count:
            raise ValueError("selection cannot exceed its evidence budget")
        if not self.dynamic and self.target_count != _MIN_EVIDENCE:
            raise ValueError("non-dynamic selection has a fixed budget of three")
        return self

    def to_public_dict(self) -> dict[str, object]:
        role_counts = {role.value: 0 for role in AuthorityRole}
        for assessment in self.assessments:
            role_counts[assessment.role.value] += 1
        return {
            "selected_count": len(self.candidates),
            "target_count": self.target_count,
            "dynamic": self.dynamic,
            "role_counts": role_counts,
        }


def _rank_key(
    candidate: CollapsedDocumentCandidate,
    assessment: CandidateRoleAssessment,
) -> tuple[int, float, int, str]:
    role_rank = {
        AuthorityRole.DIRECT_AUTHORITY: 0,
        AuthorityRole.IMPLEMENTING_OR_INTERNAL_RULE: 1,
        AuthorityRole.SUPPLEMENTARY_AUTHORITY: 2,
        AuthorityRole.BACKGROUND: 3,
        AuthorityRole.IRRELEVANT: 4,
    }[assessment.role]
    return (
        role_rank,
        -(candidate.fusion_score or 0.0),
        candidate.best_chunk_rank or 51,
        str(candidate.identity.document_version_id),
    )


def evidence_target_count(analysis: AnalyzerObservation, *, dynamic: bool) -> int:
    """Choose a justified upper target; it never creates placeholder evidence."""

    if not dynamic:
        return _MIN_EVIDENCE
    # A material unit can require one governing authority.  This has no query/case
    # identity dependency and leaves simple questions at the fixed minimum.
    return min(_MAX_DYNAMIC_EVIDENCE, max(_MIN_EVIDENCE, len(analysis.units)))


def select_evidence(
    candidates: Iterable[CollapsedDocumentCandidate],
    analysis: AnalyzerObservation,
    *,
    dynamic: bool,
) -> EvidenceSelection:
    """Select distinct documents, first preserving one candidate per material issue.

    Candidates are never duplicated to fill the budget.  The remaining slots are
    filled only with ranked, issue-aligned evidence already supplied by retrieval.
    """

    material_unit_ids = tuple(unit.unit_id for unit in analysis.units)
    unit_source_bindings = {unit.unit_id: unit.source_binding for unit in analysis.units}
    candidate_list = tuple(candidates)
    if len({candidate.identity.document_version_id for candidate in candidate_list}) != len(
        candidate_list
    ):
        raise ValueError("candidate input must be collapsed by document version")
    assessments = tuple(
        assess_candidate_role(
            candidate,
            material_unit_ids=material_unit_ids,
            unit_source_bindings=unit_source_bindings,
        )
        for candidate in candidate_list
    )
    pairs = tuple(zip(candidate_list, assessments, strict=True))
    ordered = tuple(sorted(pairs, key=lambda pair: _rank_key(*pair)))
    selected_ids: set[UUID] = set()
    selected: list[tuple[CollapsedDocumentCandidate, CandidateRoleAssessment]] = []
    target = evidence_target_count(analysis, dynamic=dynamic)

    for unit_id in material_unit_ids:
        match = next(
            (
                pair
                for pair in ordered
                if unit_id in pair[1].supported_unit_ids
                and pair[1].role is not AuthorityRole.IRRELEVANT
                and pair[0].identity.document_version_id not in selected_ids
            ),
            None,
        )
        if match is not None and len(selected) < target:
            selected.append(match)
            selected_ids.add(match[0].identity.document_version_id)

    for pair in ordered:
        if len(selected) >= target:
            break
        if (
            pair[1].role is not AuthorityRole.IRRELEVANT
            and pair[0].identity.document_version_id not in selected_ids
        ):
            selected.append(pair)
            selected_ids.add(pair[0].identity.document_version_id)

    return EvidenceSelection(
        candidates=tuple(pair[0] for pair in selected),
        assessments=tuple(pair[1] for pair in selected),
        target_count=target,
        dynamic=dynamic,
    )
