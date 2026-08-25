from uuid import uuid4

import pytest
from pydantic import ValidationError

from legal_chatbot.legal_evidence import (
    AnalysisOrigin,
    AuthorityState,
    CaseStage,
    DocumentVersionReference,
    QuestionAnalysis,
    SubIntent,
    advance_case,
    create_legal_case,
)
from legal_chatbot.legal_evidence.discovery import (
    BroadDiscoveryService,
    DiscoveryLane,
    DiscoveryLaneObservation,
    DiscoveryOutcome,
    DiscoverySettings,
    RawDiscoveryCandidate,
    collapse_candidates,
)


def _document(label: str) -> DocumentVersionReference:
    return DocumentVersionReference(
        document_id=uuid4(),
        document_version_id=uuid4(),
        provenance_record_id=uuid4(),
        source_id=f"source-{label}",
    )


def _candidate(
    document: DocumentVersionReference,
    sub_intent_id,
    lane: DiscoveryLane,
    rank: int,
    *,
    state: AuthorityState = AuthorityState.ELIGIBLE,
    provenance_verified: bool = True,
) -> RawDiscoveryCandidate:
    return RawDiscoveryCandidate(
        document=document,
        state=state,
        provenance_verified=provenance_verified,
        matched_sub_intent_ids=(sub_intent_id,),
        observations=(
            DiscoveryLaneObservation(
                lane=lane,
                rank=rank,
                score=1.0 / rank,
                query_count=1,
                elapsed_ms=1,
            ),
        ),
    )


def _analyzed_context():
    return advance_case(
        create_legal_case("private legal question"),
        CaseStage.ANALYZED,
        question_analysis=QuestionAnalysis(
            origin=AnalysisOrigin.DETERMINISTIC_FALLBACK,
            main_intent="private intent",
        ),
        sub_intents=(
            SubIntent(description="private discovery issue", retrieval_concepts=("concept",)),
        ),
    )


def test_collapse_merges_independent_lanes_by_full_identity_before_workspace_limit() -> None:
    context = _analyzed_context()
    unit_id = context.sub_intents[0].sub_intent_id
    shared = _document("shared")
    other = _document("other")

    workspace = collapse_candidates(
        (
            _candidate(shared, unit_id, DiscoveryLane.SEMANTIC_VECTOR, 3),
            _candidate(shared, unit_id, DiscoveryLane.CONTENT_FTS, 1),
            _candidate(shared, unit_id, DiscoveryLane.TITLE_METADATA, 2),
            _candidate(other, unit_id, DiscoveryLane.SEMANTIC_VECTOR, 1),
        ),
        workspace_limit=15,
    )

    assert len(workspace.documents) == 2
    shared_document = next(item for item in workspace.documents if item.document == shared)
    assert shared_document.supporting_candidate_count == 3
    assert {item.lane for item in shared_document.observations} == {
        DiscoveryLane.SEMANTIC_VECTOR,
        DiscoveryLane.CONTENT_FTS,
        DiscoveryLane.TITLE_METADATA,
    }
    assert workspace.final_evidence_selected is False


def test_workspace_limit_is_applied_after_collapse_and_order_is_deterministic() -> None:
    context = _analyzed_context()
    unit_id = context.sub_intents[0].sub_intent_id
    candidates = tuple(
        _candidate(_document(str(index)), unit_id, DiscoveryLane.SEMANTIC_VECTOR, index + 1)
        for index in range(20)
    )

    first = collapse_candidates(candidates, workspace_limit=15)
    second = collapse_candidates(tuple(reversed(candidates)), workspace_limit=15)

    assert len(first.documents) == 15
    assert first == second
    assert first.raw_candidate_count == 20


def test_unverified_provenance_is_not_admitted_as_eligible_discovery_candidate() -> None:
    context = _analyzed_context()
    with pytest.raises(ValidationError, match="unverified provenance"):
        _candidate(
            _document("invalid"),
            context.sub_intents[0].sub_intent_id,
            DiscoveryLane.SEMANTIC_VECTOR,
            1,
            provenance_verified=False,
        )


class _Reader:
    def __init__(self, candidates: tuple[RawDiscoveryCandidate, ...]) -> None:
        self._candidates = candidates
        self.requests = []

    async def discover(self, request):
        self.requests.append(request)
        return self._candidates


@pytest.mark.asyncio
async def test_service_is_default_off_and_enabled_service_advances_only_to_discovery() -> None:
    context = _analyzed_context()
    unit_id = context.sub_intents[0].sub_intent_id
    reader = _Reader((_candidate(_document("one"), unit_id, DiscoveryLane.CONTENT_FTS, 1),))

    disabled = await BroadDiscoveryService(reader).discover(context)
    enabled = await BroadDiscoveryService(
        reader, DiscoverySettings(enabled=True, workspace_limit=15)
    ).discover(context)

    assert disabled.outcome is DiscoveryOutcome.DISABLED
    assert disabled.context is context
    assert len(reader.requests) == 1
    assert enabled.outcome is DiscoveryOutcome.COMPLETED
    assert enabled.context.stage is CaseStage.DISCOVERED
    assert len(enabled.context.candidate_documents) == 1
    assert enabled.workspace.final_evidence_selected is False


def test_workspace_public_diagnostics_exclude_identity_and_query_data() -> None:
    context = _analyzed_context()
    workspace = collapse_candidates(
        (
            _candidate(
                _document("private"),
                context.sub_intents[0].sub_intent_id,
                DiscoveryLane.TITLE_METADATA,
                1,
            ),
        ),
        workspace_limit=15,
    )

    public = workspace.to_public_dict()
    assert public["workspace_document_count"] == 1
    assert public["final_evidence_selected"] is False
    assert "source-private" not in str(public)
