from types import SimpleNamespace
from uuid import uuid4

import pytest

from legal_chatbot.legal_evidence import (
    AuthorityCandidate,
    AuthorityRole,
    AuthorityState,
    CaseStage,
    CoverageEntry,
    CoverageMatrix,
    CoverageState,
    DocumentVersionReference,
    EvidenceReference,
    EvidenceUnit,
)
from legal_chatbot.legal_evidence.repair import RepairOutcome, RepairSettings, TargetedRepairService


def _context(state=AuthorityState.ELIGIBLE):
    unit = uuid4()
    document = DocumentVersionReference(
        document_id=uuid4(),
        document_version_id=uuid4(),
        provenance_record_id=uuid4(),
        source_id="VBQPPL",
    )
    return SimpleNamespace(
        stage=CaseStage.COVERAGE_REVIEWED,
        repair_count=0,
        coverage_matrix=CoverageMatrix(
            entries=(
                CoverageEntry(
                    sub_intent_id=unit,
                    state=CoverageState.UNSUPPORTED,
                    governing_authority_present=False,
                ),
            )
        ),
        candidate_documents=(SimpleNamespace(state=state, matched_sub_intent_ids=(unit,)),),
        authority_candidates=(
            AuthorityCandidate(
                document=document,
                role=(
                    AuthorityRole.GOVERNING
                    if state is AuthorityState.ELIGIBLE
                    else AuthorityRole.IRRELEVANT
                ),
                state=state,
                proposal_only=False,
                matched_sub_intent_ids=(unit,),
            ),
        ),
        sub_intents=(
            SimpleNamespace(
                sub_intent_id=unit, retrieval_concepts=("repair",), description="private issue"
            ),
        ),
        evidence_units=(),
    ), unit


class _Reader:
    def __init__(self, unit):
        self.unit = unit
        self.calls = 0

    async def repair(self, request):
        self.calls += 1
        document = SimpleNamespace(document_version_id=uuid4())
        evidence = EvidenceReference.model_construct(
            document=document, chunk_id=uuid4(), locator="Article 1"
        )
        return (
            EvidenceUnit(
                evidence=evidence,
                supported_sub_intent_ids=(self.unit,),
                authority_role=AuthorityRole.GOVERNING,
            ),
        )


@pytest.mark.asyncio
async def test_one_targeted_repair_improves_only_target_and_limits_to_one_cycle():
    context, unit = _context()
    reader = _Reader(unit)
    service = TargetedRepairService(reader, RepairSettings(enabled=True))
    result = await service.repair(context)

    assert result.outcome is RepairOutcome.EXECUTED
    assert result.repair_executed is True
    assert reader.calls == 1
    assert "private issue" not in str(result.to_public_dict())


@pytest.mark.asyncio
async def test_catalog_and_quarantine_do_not_invoke_repair_reader():
    for state, expected in (
        (AuthorityState.NOT_IN_CATALOG, RepairOutcome.NOT_IN_CATALOG),
        (AuthorityState.QUARANTINED, RepairOutcome.QUARANTINED),
    ):
        context, unit = _context(state)
        reader = _Reader(unit)
        result = await TargetedRepairService(reader, RepairSettings(enabled=True)).repair(context)
        assert result.outcome is expected
        assert reader.calls == 0
