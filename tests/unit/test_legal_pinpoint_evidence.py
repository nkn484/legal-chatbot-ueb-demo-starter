from uuid import uuid4

import pytest

from legal_chatbot.legal_evidence import (
    AnalysisOrigin,
    AuthorityCandidate,
    AuthorityFamily,
    AuthorityRole,
    AuthorityState,
    CandidateDocument,
    CaseStage,
    DocumentVersionReference,
    EvidenceReference,
    QuestionAnalysis,
    SubIntent,
    advance_case,
    create_legal_case,
)
from legal_chatbot.legal_evidence.pinpoint import (
    PinpointEvidenceService,
    PinpointOutcome,
    PinpointSettings,
    RawPinpointEvidence,
)


def _document(label: str) -> DocumentVersionReference:
    return DocumentVersionReference(
        document_id=uuid4(),
        document_version_id=uuid4(),
        provenance_record_id=uuid4(),
        source_id=label,
    )


def _context():
    first, second = _document("one"), _document("two")
    received = create_legal_case("private question")
    analyzed = advance_case(
        received,
        CaseStage.ANALYZED,
        question_analysis=QuestionAnalysis(
            origin=AnalysisOrigin.DETERMINISTIC_FALLBACK,
            main_intent="private intent",
        ),
        sub_intents=(SubIntent(description="issue one", retrieval_concepts=("one",)),),
    )
    unit_id = analyzed.sub_intents[0].sub_intent_id
    discovered = advance_case(
        analyzed,
        CaseStage.DISCOVERED,
        candidate_documents=(
            CandidateDocument(
                document=first, state=AuthorityState.ELIGIBLE, matched_sub_intent_ids=(unit_id,)
            ),
            CandidateDocument(
                document=second, state=AuthorityState.ELIGIBLE, matched_sub_intent_ids=()
            ),
        ),
    )
    reviewed = advance_case(
        discovered,
        CaseStage.AUTHORITY_REVIEWED,
        authority_candidates=(
            AuthorityCandidate(
                document=first,
                role=AuthorityRole.GOVERNING,
                state=AuthorityState.ELIGIBLE,
                proposal_only=False,
            ),
            AuthorityCandidate(
                document=second,
                role=AuthorityRole.BACKGROUND,
                state=AuthorityState.ELIGIBLE,
                proposal_only=False,
            ),
        ),
    )
    return (
        advance_case(
            reviewed,
            CaseStage.FAMILIES_RESOLVED,
            authority_families=(
                AuthorityFamily(
                    document_version_ids=(first.document_version_id, second.document_version_id)
                ),
            ),
        ),
        first,
        second,
        unit_id,
    )


class _Reader:
    def __init__(self, items):
        self.items = items
        self.requests = []

    async def read(self, request):
        self.requests.append(request)
        return self.items


@pytest.mark.asyncio
async def test_pinpoint_reader_is_default_off_and_enabled_reader_preserves_locator_provenance() -> (
    None
):
    context, first, _, unit_id = _context()
    evidence = EvidenceReference(document=first, chunk_id=uuid4(), locator="Article 3")
    reader = _Reader(
        (
            RawPinpointEvidence(
                evidence=evidence,
                sub_intent_id=unit_id,
                authority_role=AuthorityRole.GOVERNING,
                rank=1,
            ),
        )
    )

    disabled = await PinpointEvidenceService(reader).read_context(context)
    enabled = await PinpointEvidenceService(reader, PinpointSettings(enabled=True)).read_context(
        context
    )

    assert disabled.result.outcome is PinpointOutcome.DISABLED
    assert enabled.context.stage is CaseStage.EVIDENCE_READ
    assert len(enabled.result.evidence_units) == 1
    assert enabled.result.evidence_units[0].evidence == evidence
    assert enabled.result.evidence_units[0].authority_role is AuthorityRole.GOVERNING


@pytest.mark.asyncio
async def test_pinpoint_rejects_outside_evidence_and_deduplicates() -> (
    None
):
    context, first, second, unit_id = _context()
    allowed = EvidenceReference(document=first, chunk_id=uuid4(), locator="Article 3")
    outside = EvidenceReference(document=second, chunk_id=uuid4(), locator="Article 4")
    reader = _Reader(
        (
            RawPinpointEvidence(
                evidence=allowed,
                sub_intent_id=unit_id,
                authority_role=AuthorityRole.GOVERNING,
                rank=1,
            ),
        )
    )
    service = PinpointEvidenceService(
        reader, PinpointSettings(enabled=True, max_evidence_per_sub_intent=5)
    )

    result = await service.read(context)
    assert len(result.evidence_units) == 1
    reader.items = (
        RawPinpointEvidence(
            evidence=outside, sub_intent_id=unit_id, authority_role=AuthorityRole.BACKGROUND, rank=1
        ),
    )
    with pytest.raises(ValueError, match="outside"):
        await service.read(context)


@pytest.mark.asyncio
async def test_zero_eligible_family_advances_to_empty_evidence_instead_of_crashing() -> None:
    context, _, _, _ = _context()
    no_family = context.model_copy(update={"authority_families": ()})
    result = await PinpointEvidenceService(
        _Reader(()), PinpointSettings(enabled=True)
    ).read_context(no_family)

    assert result.result.outcome is PinpointOutcome.NO_ELIGIBLE_FAMILY
    assert result.context.stage is CaseStage.EVIDENCE_READ
    assert result.context.evidence_units == ()
