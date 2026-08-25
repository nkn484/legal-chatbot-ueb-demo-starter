"""Deterministic P11 guard for claim support, qualifications, and frozen evidence identity."""

from __future__ import annotations

from dataclasses import dataclass

from legal_chatbot.legal_evidence.composition.models import ClaimKind, CompositionResult
from legal_chatbot.legal_evidence.models import CoverageState

from .models import ReviewFinding, ReviewFindingCode


@dataclass(frozen=True)
class ReviewGuardAssessment:
    findings: tuple[ReviewFinding, ...]
    evidence_identity_preserved: bool

    @property
    def passes(self) -> bool:
        return not self.findings and self.evidence_identity_preserved


def evidence_identity(evidence_units) -> tuple[tuple[object, ...], ...]:
    """Represent only immutable selected-evidence identity, never excerpt text."""

    return tuple(
        (
            unit.evidence.document.document_id,
            unit.evidence.document.document_version_id,
            unit.evidence.document.provenance_record_id,
            unit.evidence.chunk_id,
            unit.evidence.locator,
            unit.authority_role.value,
            tuple(sorted(unit.supported_sub_intent_ids)),
        )
        for unit in evidence_units
    )


class DeterministicReviewReleaseGuard:
    """Never allow reviewer output to override missing support or retained limitations."""

    def assess(
        self,
        context,
        draft: CompositionResult,
        *,
        selected_evidence_identity: tuple[tuple[object, ...], ...],
    ) -> ReviewGuardAssessment:
        findings: list[ReviewFinding] = []
        preserved = selected_evidence_identity == evidence_identity(context.evidence_units)
        if not preserved:
            findings.append(ReviewFinding(code=ReviewFindingCode.EVIDENCE_PACK_DRIFT))
        if not draft.enabled or draft.answer != context.answer_draft.text:
            findings.append(ReviewFinding(code=ReviewFindingCode.COMPOSITION_DRAFT_MISMATCH))
            return ReviewGuardAssessment(tuple(findings), preserved)

        claim_numbers = tuple(item.claim_index for item in draft.claims)
        if claim_numbers != tuple(range(len(draft.claims))):
            findings.append(ReviewFinding(code=ReviewFindingCode.CLAIM_REFERENCE_INVALID))

        for claim in draft.claims:
            if any(index >= len(context.sub_intents) for index in claim.sub_intent_indices) or any(
                index >= len(context.evidence_units) for index in claim.evidence_indices
            ):
                findings.append(
                    ReviewFinding(
                        code=ReviewFindingCode.CLAIM_REFERENCE_INVALID,
                        claim_indices=(claim.claim_index,),
                    )
                )
                continue
            if claim.kind not in {ClaimKind.SOURCE_FACT, ClaimKind.SUPPORTED_INTERPRETATION}:
                continue
            if not claim.sub_intent_indices or not claim.evidence_indices:
                findings.append(
                    ReviewFinding(
                        code=ReviewFindingCode.UNSUPPORTED_MATERIAL_CLAIM,
                        claim_indices=(claim.claim_index,),
                        sub_intent_indices=claim.sub_intent_indices,
                    )
                )
                continue
            for sub_intent_index in claim.sub_intent_indices:
                sub_intent_id = context.sub_intents[sub_intent_index].sub_intent_id
                if not any(
                    sub_intent_id in context.evidence_units[evidence_index].supported_sub_intent_ids
                    for evidence_index in claim.evidence_indices
                ):
                    findings.append(
                        ReviewFinding(
                            code=ReviewFindingCode.UNSUPPORTED_MATERIAL_CLAIM,
                            claim_indices=(claim.claim_index,),
                            sub_intent_indices=(sub_intent_index,),
                            evidence_indices=claim.evidence_indices,
                        )
                    )

        coverage = {entry.sub_intent_id: entry for entry in context.coverage_matrix.entries}
        for sub_intent_index, sub_intent in enumerate(context.sub_intents):
            entry = coverage[sub_intent.sub_intent_id]
            if entry.state is CoverageState.SUPPORTED:
                continue
            qualified = any(
                claim.kind in {ClaimKind.LIMITATION, ClaimKind.NEXT_CHECK}
                and sub_intent_index in claim.sub_intent_indices
                for claim in draft.claims
            )
            if not qualified:
                findings.append(
                    ReviewFinding(
                        code=ReviewFindingCode.UNRESOLVED_ISSUE_NOT_QUALIFIED,
                        sub_intent_indices=(sub_intent_index,),
                    )
                )
        return ReviewGuardAssessment(tuple(_deduplicate(findings)), preserved)


def _deduplicate(findings: list[ReviewFinding]) -> list[ReviewFinding]:
    unique: list[ReviewFinding] = []
    seen: set[tuple[object, ...]] = set()
    for finding in findings:
        key = (
            finding.code,
            finding.claim_indices,
            finding.sub_intent_indices,
            finding.evidence_indices,
        )
        if key not in seen:
            seen.add(key)
            unique.append(finding)
    return unique


__all__ = [
    "DeterministicReviewReleaseGuard",
    "ReviewGuardAssessment",
    "evidence_identity",
]
