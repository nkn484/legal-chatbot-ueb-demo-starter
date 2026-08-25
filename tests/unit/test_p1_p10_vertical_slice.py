from uuid import uuid4

import pytest

from legal_chatbot.legal_evidence import (
    AuthorityRole,
    AuthorityState,
    DocumentVersionReference,
    EvidenceReference,
    EvidenceUnit,
)
from legal_chatbot.legal_evidence.analyzer import (
    LegalQuestionAnalyzerSettings,
    LLMLegalQuestionAnalyzer,
)
from legal_chatbot.legal_evidence.authority import (
    AuthorityMetadata,
    AuthorityReviewService,
    AuthorityReviewSettings,
)
from legal_chatbot.legal_evidence.completeness import (
    CompletenessReviewService,
    CompletenessSettings,
)
from legal_chatbot.legal_evidence.composition import (
    CompositionEvidence,
    DeterministicEvidenceBoundComposer,
)
from legal_chatbot.legal_evidence.discovery import (
    BroadDiscoveryService,
    DiscoveryLane,
    DiscoveryLaneObservation,
    DiscoveryReadRequest,
    DiscoverySettings,
    RawDiscoveryCandidate,
)
from legal_chatbot.legal_evidence.pinpoint import (
    PinpointEvidenceService,
    PinpointSettings,
    RawPinpointEvidence,
)
from legal_chatbot.legal_evidence.relations import (
    RelationInvestigationService,
    RelationInvestigationSettings,
)
from legal_chatbot.legal_evidence.repair import RepairSettings, TargetedRepairService
from legal_chatbot.legal_evidence.selection import (
    CoverageFirstEvidenceSelector,
    EvidenceSelectionSettings,
)
from legal_chatbot.legal_evidence.vertical_slice import P1P10VerticalSliceInvestigator


class _DiscoveryReader:
    def __init__(self, document: DocumentVersionReference) -> None:
        self._document = document

    async def discover(self, request: DiscoveryReadRequest):
        return (
            RawDiscoveryCandidate(
                document=self._document,
                state=AuthorityState.ELIGIBLE,
                provenance_verified=True,
                matched_sub_intent_ids=(request.sub_intent_id,),
                observations=(
                    DiscoveryLaneObservation(
                        lane=DiscoveryLane.CONTENT_FTS,
                        rank=1,
                        score=1.0,
                        query_count=1,
                        elapsed_ms=1.0,
                    ),
                ),
            ),
        )


class _MetadataReader:
    async def load(self, candidates):
        return tuple(
            AuthorityMetadata(
                document=candidate.document,
                discovery_state=candidate.state,
                provenance_valid=True,
                scope_compatible=True,
                source_binding_compatible=True,
                status_eligible=True,
                matched_sub_intent_ids=candidate.matched_sub_intent_ids,
            )
            for candidate in candidates
        )


class _PinpointReader:
    async def read(self, request):
        return (
            RawPinpointEvidence(
                evidence=EvidenceReference(
                    document=request.documents[0], chunk_id=uuid4(), locator="chunk:0"
                ),
                sub_intent_id=request.sub_intent_id,
                authority_role=AuthorityRole.BACKGROUND,
                rank=1,
            ),
        )


class _RepairReader:
    async def repair(self, request):
        return (
            EvidenceUnit(
                evidence=EvidenceReference(
                    document=request.documents[0], chunk_id=uuid4(), locator="chunk:1"
                ),
                supported_sub_intent_ids=(request.sub_intent_id,),
                authority_role=request.authority_roles[0],
            ),
        )


class _CompositionReader:
    async def load(self, units):
        return tuple(CompositionEvidence(unit=unit, excerpt="untrusted evidence") for unit in units)


@pytest.mark.asyncio
async def test_vertical_slice_carries_p4_state_into_p5_p6_and_stops_before_p11():
    document = DocumentVersionReference(
        document_id=uuid4(),
        document_version_id=uuid4(),
        provenance_record_id=uuid4(),
        source_id="VBQPPL",
    )
    investigator = P1P10VerticalSliceInvestigator(
        analyzer=LLMLegalQuestionAnalyzer(
            None,
            settings=LegalQuestionAnalyzerSettings(enabled=False),
        ),
        discovery=BroadDiscoveryService(
            _DiscoveryReader(document), DiscoverySettings(enabled=True)
        ),
        authority_metadata=_MetadataReader(),
        authority=AuthorityReviewService(None, AuthorityReviewSettings(enabled=False)),
        relations=RelationInvestigationService(None, RelationInvestigationSettings(enabled=False)),
        pinpoint=PinpointEvidenceService(_PinpointReader(), PinpointSettings(enabled=True)),
        completeness=CompletenessReviewService(None, CompletenessSettings(enabled=False)),
        repair=TargetedRepairService(_RepairReader(), RepairSettings(enabled=True)),
        selector=CoverageFirstEvidenceSelector(EvidenceSelectionSettings(enabled=True)),
        composer=DeterministicEvidenceBoundComposer(_CompositionReader()),
    )

    trace = await investigator.investigate_with_trace("Quy trinh mua sam tai UEB?")

    assert trace.context.stage.value == "ANSWER_DRAFTED"
    assert trace.context.repair_count == 1
    assert (
        trace.authority.context.authority_candidates
        == trace.relations.context.authority_candidates
    )
    assert trace.pinpoint.context.authority_families == trace.relations.context.authority_families
    assert trace.context.review_result is None
    assert trace.context.answer_draft is not None
