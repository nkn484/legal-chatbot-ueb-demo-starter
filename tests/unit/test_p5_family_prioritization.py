from types import SimpleNamespace
from uuid import uuid4

from legal_chatbot.legal_evidence import (
    ApplicabilityState,
    AuthorityAssessment,
    AuthorityCandidate,
    AuthorityRole,
    AuthorityState,
    DocumentVersionReference,
    SubIntent,
)
from legal_chatbot.legal_evidence.relations import RelationInvestigationService, build_families


def _document(*, document_id=None) -> DocumentVersionReference:
    return DocumentVersionReference(
        document_id=document_id or uuid4(),
        document_version_id=uuid4(),
        provenance_record_id=uuid4(),
        source_id="UEB",
    )


def _candidate(document: DocumentVersionReference) -> AuthorityCandidate:
    return AuthorityCandidate(
        document=document,
        role=AuthorityRole.GOVERNING,
        state=AuthorityState.ELIGIBLE,
        applicability=ApplicabilityState.CURRENT_EFFECT_UNVERIFIED,
        proposal_only=True,
    )


def test_priority_keeps_cross_subintent_coverage_inside_fifteen_candidate_boundary() -> None:
    first = SubIntent(code="AUTHORITY", description="authority", retrieval_concepts=("thẩm quyền",))
    second = SubIntent(code="PROCEDURE", description="procedure", retrieval_concepts=("quy trình",))
    candidates = tuple(_candidate(_document()) for _ in range(16))
    assessments = tuple(
        AuthorityAssessment(
            document=candidate.document,
            sub_intent_id=first.sub_intent_id if index < 15 else second.sub_intent_id,
            proposed_role=AuthorityRole.GOVERNING,
            role=AuthorityRole.GOVERNING,
            state=AuthorityState.ELIGIBLE,
            applicability=ApplicabilityState.CURRENT_EFFECT_UNVERIFIED,
        )
        for index, candidate in enumerate(candidates)
    )
    context = SimpleNamespace(
        authority_candidates=candidates,
        authority_assessments=assessments,
        sub_intents=(first, second),
    )

    selected, pruned = RelationInvestigationService._prioritize_for_context(context)

    assert len(selected) == 15
    assert candidates[-1] in selected
    assert len(pruned) == 1


def test_same_legal_document_versions_consolidate_without_relation_inference() -> None:
    document_id = uuid4()
    first = _candidate(_document(document_id=document_id))
    second = _candidate(_document(document_id=document_id))

    families = build_families((first, second), ())

    assert len(families) == 1
    assert set(families[0].document_version_ids) == {
        first.document.document_version_id,
        second.document.document_version_id,
    }
