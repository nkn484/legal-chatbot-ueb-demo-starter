"""Focused contracts for the generalized legal-answer quality core."""

from __future__ import annotations

import json
from uuid import UUID, uuid5

from legal_chatbot.retrieval.models import ResolvedCitation
from legal_chatbot.retrieval.quality_repair.analyzer import (
    AnalyzerObservation,
    AnalyzerUnit,
    GenericIntent,
    LegalQuestionAnalyzer,
    QueryComplexity,
    SourceScope,
)
from legal_chatbot.retrieval.quality_repair.candidate_roles import AuthorityRole
from legal_chatbot.retrieval.quality_repair.claim_validation import (
    ClaimValidationStatus,
    MaterialClaim,
    validate_material_claims,
)
from legal_chatbot.retrieval.quality_repair.coverage import (
    EvidenceCoverageStatus,
    build_coverage_matrix,
)
from legal_chatbot.retrieval.quality_repair.evidence_budget import select_evidence
from legal_chatbot.retrieval.quality_repair.evidence_pack import (
    SelectedLegalAuthority,
    StructuredEvidencePack,
    derive_limitations,
)
from legal_chatbot.retrieval.quality_repair.models import (
    CandidateEvidence,
    CollapsedDocumentCandidate,
    DocumentIdentity,
    LaneAggregate,
    LaneObservation,
    ProvenanceType,
    RetrievalLane,
    SourceId,
    SourceScopeObservation,
)
from legal_chatbot.retrieval.quality_repair.repair import plan_targeted_repair


def _uuid(value: str) -> UUID:
    return uuid5(UUID("12345678-1234-5678-1234-567812345678"), value)


def _analysis() -> AnalyzerObservation:
    units = tuple(
        AnalyzerUnit(
            unit_id=f"u0{index}",
            intent=GenericIntent.PROCEDURE,
            source_scope=SourceScope.NONE,
        )
        for index in range(1, 5)
    )
    return AnalyzerObservation(
        intent=GenericIntent.MULTI_STAGE_PROCESS,
        complexity=QueryComplexity.MULTI_INTENT,
        source_scope=SourceScope.NONE,
        units=units,
    )


def _candidate(
    name: str,
    *unit_ids: str,
    provenance_type: ProvenanceType = ProvenanceType.SOURCE_FETCH,
) -> CollapsedDocumentCandidate:
    identity = DocumentIdentity(
        document_id=_uuid(f"document-{name}"),
        document_version_id=_uuid(f"version-{name}"),
        source_id=SourceId.VBQPPL,
        external_id=f"external-{name}",
        version_number=1,
        provenance_record_id=_uuid(f"provenance-{name}"),
        provenance_type=provenance_type,
        latest_ingested=True,
    )
    evidence = CandidateEvidence(
        chunk_id=_uuid(f"chunk-{name}"),
        identity=identity,
        ordinal=1,
        observations=(
            LaneObservation(
                lane=RetrievalLane.SEMANTIC,
                rank=1,
                score=0.9,
                query_count=1,
                elapsed_ms=1.0,
                rows_returned=1,
            ),
        ),
        unit_ids=unit_ids,
        source_scope=SourceScopeObservation.NONE,
        eligible=True,
    )
    return CollapsedDocumentCandidate(
        identity=identity,
        representative=evidence,
        supporting_chunk_count=0,
        best_chunk_rank=1,
        best_chunk_score=0.9,
        lane_aggregates=(
            LaneAggregate(lane=RetrievalLane.SEMANTIC, best_rank=1, best_score=0.9),
        ),
        merged_unit_ids=unit_ids,
        fusion_score=0.9,
    )


def _citation(candidate: CollapsedDocumentCandidate) -> ResolvedCitation:
    identity = candidate.identity
    return ResolvedCitation(
        citation_id=_uuid(f"citation-{identity.document_version_id}"),
        retrieval_run_id=_uuid("retrieval-run"),
        document_chunk_id=candidate.representative.chunk_id,
        document_version_id=identity.document_version_id,
        document_id=identity.document_id,
        source_provenance_record_id=identity.provenance_record_id,
        source_id=identity.source_id.value,
        external_id=identity.external_id,
    )


def test_dynamic_selection_preserves_every_sub_intent_without_padding() -> None:
    analysis = _analysis()
    candidates = tuple(_candidate(f"item-{index}", f"u0{index}") for index in range(1, 5))

    dynamic = select_evidence(candidates, analysis, dynamic=True)
    fixed = select_evidence(candidates, analysis, dynamic=False)

    assert dynamic.target_count == 4
    assert {item.supported_unit_ids for item in dynamic.assessments} == {
        ("u01",),
        ("u02",),
        ("u03",),
        ("u04",),
    }
    assert len(fixed.candidates) == 3
    assert len({item.identity.document_version_id for item in dynamic.candidates}) == 4


def test_manual_provenance_is_never_promoted_to_direct_authority() -> None:
    analysis = _analysis()
    manual = _candidate("manual", "u01", provenance_type=ProvenanceType.MANUAL_SNAPSHOT)

    selection = select_evidence((manual,), analysis, dynamic=True)
    coverage = build_coverage_matrix(
        analysis, selection, active_source_ids=(SourceId.VBQPPL,)
    )

    assert selection.assessments[0].role is AuthorityRole.SUPPLEMENTARY_AUTHORITY
    assert coverage.entries[0].status is EvidenceCoverageStatus.PARTIALLY_SUPPORTED


def test_repair_is_single_gap_targeted_and_private() -> None:
    analysis = LegalQuestionAnalyzer().analyze(
        "Thủ tục đăng ký bảo hiểm là gì; sau đó nộp hồ sơ ở đâu; rồi khiếu nại thế nào?"
    )
    selection = select_evidence((_candidate("one", "u01"),), analysis, dynamic=True)
    coverage = build_coverage_matrix(
        analysis, selection, active_source_ids=(SourceId.VBQPPL,)
    )

    repair = plan_targeted_repair(analysis, coverage)

    assert repair is not None
    assert repair.unit_id == "u02"
    assert repair.query_text
    assert "u02" not in json.dumps(repair.model_dump(mode="json"))
    assert repair.query_text not in json.dumps(repair.model_dump(mode="json"))


def test_pack_and_claim_validation_qualify_or_reject_without_provider_review() -> None:
    analysis = _analysis()
    candidate = _candidate("authority", "u01")
    selection = select_evidence((candidate,), analysis, dynamic=True)
    coverage = build_coverage_matrix(
        analysis, selection, active_source_ids=(SourceId.VBQPPL,)
    )
    authority = SelectedLegalAuthority(
        citation=_citation(candidate),
        excerpt="private legal evidence",
        role=selection.assessments[0].role,
        supported_unit_ids=("u01",),
        applicability_uncertain=True,
    )
    pack = StructuredEvidencePack(
        analysis=analysis,
        authorities=(authority,),
        coverage=coverage,
        limitations=derive_limitations(coverage, (authority,)),
    )
    result = validate_material_claims(
        (
            MaterialClaim(
                claim_id="supported", unit_ids=("u01",), citation_ids=(authority.citation_id,)
            ),
            MaterialClaim(claim_id="missing", unit_ids=("u02",), citation_ids=()),
        ),
        pack,
    )

    assert [item.status for item in result.claims] == [
        ClaimValidationStatus.SUPPORTED_WITH_QUALIFICATION,
        ClaimValidationStatus.INSUFFICIENT_CONTEXT,
    ]
    serialized = json.dumps(pack.model_dump(mode="json"), ensure_ascii=False)
    assert "private legal evidence" not in serialized
    assert "u01" not in serialized
