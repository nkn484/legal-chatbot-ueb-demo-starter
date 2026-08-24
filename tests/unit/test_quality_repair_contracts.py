import json
from math import nan
from uuid import uuid4

import pytest
from pydantic import ValidationError

from legal_chatbot.retrieval.quality_repair.models import (
    CandidateEvidence,
    CollapsedDocumentCandidate,
    DocumentIdentity,
    LaneObservation,
    OpportunityTag,
    ProvenanceType,
    RetrievalLane,
    SourceId,
    SourceScopeObservation,
)
from legal_chatbot.retrieval.quality_repair.strategy import (
    CandidatePoolSelectionMode,
    EvidencePaddingPolicy,
    QualityRepairStrategy,
    materialize_strategy,
)


def _identity() -> DocumentIdentity:
    return DocumentIdentity(
        document_id=uuid4(),
        document_version_id=uuid4(),
        source_id=SourceId.VBQPPL,
        external_id="private-external-id",
        document_number_normalized="01/2026/QD",
        title="Private title",
        version_number=1,
        provenance_record_id=uuid4(),
        provenance_type=ProvenanceType.SOURCE_FETCH,
        latest_ingested=True,
    )


def _candidate(identity: DocumentIdentity | None = None) -> CandidateEvidence:
    return CandidateEvidence(
        chunk_id=uuid4(),
        identity=identity or _identity(),
        ordinal=0,
        observations=(
            LaneObservation(
                lane=RetrievalLane.SEMANTIC,
                rank=1,
                score=1,
                query_count=1,
                elapsed_ms=1,
                rows_returned=1,
            ),
        ),
        unit_ids=("private-unit",),
        source_scope=SourceScopeObservation.NONE,
        eligible=True,
    )


def test_candidate_contract_rejects_nonfinite_scores_and_duplicate_lanes_or_unit_ids() -> None:
    with pytest.raises(ValidationError):
        LaneObservation(
            lane=RetrievalLane.SEMANTIC,
            rank=1,
            score=nan,
            query_count=1,
            elapsed_ms=1,
            rows_returned=1,
        )
    observation = LaneObservation(
        lane=RetrievalLane.SEMANTIC, rank=1, score=1, query_count=1, elapsed_ms=1, rows_returned=1
    )
    with pytest.raises(ValidationError):
        CandidateEvidence(
            chunk_id=uuid4(),
            identity=_identity(),
            ordinal=0,
            observations=(observation, observation),
            unit_ids=("opaque",),
            source_scope=SourceScopeObservation.NONE,
            eligible=True,
        )
    with pytest.raises(ValidationError):
        CandidateEvidence(
            chunk_id=uuid4(),
            identity=_identity(),
            ordinal=0,
            observations=(observation,),
            unit_ids=("opaque", "opaque"),
            source_scope=SourceScopeObservation.NONE,
            eligible=True,
        )


def test_public_contract_diagnostics_exclude_private_identifiers_and_text() -> None:
    candidate = _candidate()
    identity = candidate.identity
    serialized = json.dumps(candidate.model_dump(mode="json"))
    public = json.dumps(candidate.to_public_dict())
    representation = repr(candidate)
    sentinels = (
        str(candidate.chunk_id),
        str(identity.document_id),
        str(identity.document_version_id),
        str(identity.provenance_record_id),
        "private-external-id",
        "01/2026/QD",
        "Private title",
        "private-unit",
    )
    for sentinel in sentinels:
        assert sentinel not in serialized
        assert sentinel not in public
        assert sentinel not in representation


def test_collapsed_candidate_requires_matching_representative_identity() -> None:
    candidate = _candidate()
    with pytest.raises(ValidationError):
        CollapsedDocumentCandidate(
            identity=_identity(),
            representative=candidate,
            supporting_chunk_count=1,
        )
    different_provenance = candidate.identity.model_copy(update={"provenance_record_id": uuid4()})
    with pytest.raises(ValidationError, match="fully match"):
        CollapsedDocumentCandidate(
            identity=different_provenance,
            representative=candidate,
            supporting_chunk_count=1,
        )


def test_opportunity_tags_keep_unit_and_source_ids_private() -> None:
    tag = OpportunityTag(
        unit_id="private-opportunity-unit",
        source_scope=SourceScopeObservation.EXPLICIT_SOURCE,
        source_ids=(SourceId.VBQPPL,),
    )
    serialized = json.dumps(tag.model_dump(mode="json"))
    assert "private-opportunity-unit" not in serialized
    assert SourceId.VBQPPL.value not in serialized
    assert tag.to_public_dict() == {"source_scope": "EXPLICIT_SOURCE", "source_count": 1}


def test_strategy_enforces_phase_a_pool_evidence_and_no_padding_contract() -> None:
    values = {
        "name": "test_profile",
        "strategy_version": "quality-retrieval-a1-v1",
        "candidate_pool_sizes": (8,),
        "candidate_pool_selection_mode": CandidatePoolSelectionMode.FIXED,
        "enabled_lanes": (RetrievalLane.SEMANTIC,),
        "lane_weights": (1.0,),
    }
    strategy = QualityRepairStrategy.model_validate(values)
    assert strategy.final_evidence_min == 3
    assert strategy.final_evidence_max == 3
    assert strategy.evidence_padding_policy is EvidencePaddingPolicy.NO_PADDING
    with pytest.raises(ValidationError):
        QualityRepairStrategy.model_validate(values | {"candidate_pool_sizes": (7,)})
    with pytest.raises(ValidationError):
        QualityRepairStrategy.model_validate(values | {"repair_rounds": 1})
    with pytest.raises(ValidationError, match="final evidence bounds"):
        QualityRepairStrategy.model_validate(values | {"final_evidence_max": 6})
    dynamic = QualityRepairStrategy.model_validate(
        values | {"dynamic_evidence_enabled": True, "final_evidence_max": 6}
    )
    assert dynamic.final_evidence_max == 6


def test_materialization_requires_a_declared_pool_and_excludes_the_control() -> None:
    materialized = materialize_strategy("quality_retrieval_hybrid_v1", 12)
    assert materialized.selected_pool == 12
    with pytest.raises(ValueError, match="selected_pool"):
        materialize_strategy("quality_retrieval_document_collapse_v1", 12)
    with pytest.raises(ValueError, match="materializable"):
        materialize_strategy("quality_retrieval_current_default_v1", 8)
