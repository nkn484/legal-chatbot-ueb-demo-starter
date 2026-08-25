from uuid import uuid4

import pytest
from pydantic import ValidationError

from legal_chatbot.legal_evidence import (
    AnalysisOrigin,
    CaseStage,
    DocumentVersionReference,
    EvidenceReference,
    LegalCaseTransitionError,
    QuestionAnalysis,
    RelationHint,
    RelationType,
    RelationVerification,
    SubIntent,
    advance_case,
    create_legal_case,
    record_reviewed_relation,
    verified_applicability_state,
    verify_relation,
)
from legal_chatbot.legal_evidence.models import ApplicabilityState


def _evidence() -> EvidenceReference:
    return EvidenceReference(
        document=DocumentVersionReference(
            document_id=uuid4(),
            document_version_id=uuid4(),
            provenance_record_id=uuid4(),
            source_id="VBQPPL",
        ),
        chunk_id=uuid4(),
        locator="Article 1",
    )


def _analyzed_context():
    return advance_case(
        create_legal_case("private question"),
        CaseStage.ANALYZED,
        question_analysis=QuestionAnalysis(
            origin=AnalysisOrigin.DETERMINISTIC_FALLBACK,
            main_intent="private legal intent",
        ),
        sub_intents=(SubIntent(description="private material sub-intent"),),
    )


def test_case_transitions_are_immutable_and_sequential() -> None:
    received = create_legal_case("private question")
    analyzed = advance_case(
        received,
        CaseStage.ANALYZED,
        question_analysis=QuestionAnalysis(
            origin=AnalysisOrigin.DETERMINISTIC_FALLBACK,
            main_intent="private legal intent",
        ),
        sub_intents=(SubIntent(description="private material sub-intent"),),
    )

    assert received.stage is CaseStage.RECEIVED
    assert analyzed.stage is CaseStage.ANALYZED
    assert received.case_id == analyzed.case_id
    assert received is not analyzed
    with pytest.raises(LegalCaseTransitionError, match="exactly one stage"):
        advance_case(received, CaseStage.DISCOVERED)


def test_transition_rejects_question_or_identity_replacement() -> None:
    with pytest.raises(LegalCaseTransitionError, match="immutable field"):
        advance_case(_analyzed_context(), CaseStage.DISCOVERED, question_text="replacement")
    with pytest.raises(LegalCaseTransitionError, match="immutable field"):
        advance_case(_analyzed_context(), CaseStage.DISCOVERED, case_id=uuid4())


def test_relation_hint_cannot_be_constructed_as_verified_fact() -> None:
    with pytest.raises(ValidationError, match="relation hints must remain proposal-only"):
        RelationHint(
            subject_document_version_id=uuid4(),
            object_document_version_id=uuid4(),
            relation_type=RelationType.AMENDS,
            verification=RelationVerification.EVIDENCE_VERIFIED,
        )


def test_evidence_reference_is_required_to_promote_relation_and_record_review() -> None:
    hint = RelationHint(
        subject_document_version_id=uuid4(),
        object_document_version_id=uuid4(),
        relation_type=RelationType.REPLACES,
    )

    verified = verify_relation(hint, _evidence())
    reviewed = record_reviewed_relation(verified, reviewed_by="legal-reviewer-001")

    assert verified.verification is RelationVerification.EVIDENCE_VERIFIED
    assert reviewed.verification is RelationVerification.REVIEWED
    assert reviewed.evidence == verified.evidence
    with pytest.raises(LegalCaseTransitionError, match="only evidence-verified"):
        record_reviewed_relation(reviewed, reviewed_by="legal-reviewer-002")


def test_verified_applicability_requires_unique_evidence() -> None:
    evidence = _evidence()

    assert verified_applicability_state((evidence,)) is ApplicabilityState.VERIFIED
    with pytest.raises(LegalCaseTransitionError, match="requires evidence"):
        verified_applicability_state(())
    with pytest.raises(LegalCaseTransitionError, match="must be unique"):
        verified_applicability_state((evidence, evidence))
