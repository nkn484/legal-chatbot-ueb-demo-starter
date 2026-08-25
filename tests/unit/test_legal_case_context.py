import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from legal_chatbot.legal_evidence import (
    AnalysisOrigin,
    AuthorityCandidate,
    AuthorityRole,
    AuthorityState,
    CaseStage,
    DocumentVersionReference,
    LegalCaseContext,
    QuestionAnalysis,
    SubIntent,
    create_legal_case,
    map_legacy_authority_role,
    map_legacy_coverage_state,
)
from legal_chatbot.legal_evidence.models import ApplicabilityState, CoverageState


def _document() -> DocumentVersionReference:
    return DocumentVersionReference(
        document_id=uuid4(),
        document_version_id=uuid4(),
        provenance_record_id=uuid4(),
        source_id="VBQPPL",
    )


def test_case_context_excludes_user_text_identifiers_and_private_analysis_from_serialization() -> (
    None
):
    question = "private user question about a legal event"
    intent = "private legal intent"
    sub_intent = SubIntent(description="private material sub-intent")
    analysis = QuestionAnalysis(origin=AnalysisOrigin.LLM_PROPOSAL, main_intent=intent)
    document = _document()
    context = LegalCaseContext(
        question_text=question,
        stage=CaseStage.ANALYZED,
        question_analysis=analysis,
        sub_intents=(sub_intent,),
        authority_candidates=(
            AuthorityCandidate(
                document=document,
                role=AuthorityRole.GOVERNING,
                state=AuthorityState.ELIGIBLE,
            ),
        ),
    )

    serialized = json.dumps(context.model_dump(mode="json"), ensure_ascii=False)
    public = json.dumps(context.to_public_dict(), ensure_ascii=False)
    representation = repr(context)
    sentinels = (
        question,
        intent,
        sub_intent.description,
        str(context.case_id),
        str(sub_intent.sub_intent_id),
        str(document.document_id),
        str(document.document_version_id),
        str(document.provenance_record_id),
        "VBQPPL",
    )
    for sentinel in sentinels:
        assert sentinel not in serialized
        assert sentinel not in public
        assert sentinel not in representation


def test_case_context_limits_material_sub_intents_to_four() -> None:
    with pytest.raises(ValidationError, match="at most 4 items"):
        LegalCaseContext(
            question_text="private question",
            stage=CaseStage.ANALYZED,
            question_analysis=QuestionAnalysis(
                origin=AnalysisOrigin.DETERMINISTIC_FALLBACK,
                main_intent="private intent",
            ),
            sub_intents=tuple(SubIntent(description=f"private item {index}") for index in range(5)),
        )


def test_legacy_compatibility_mappings_remain_proposal_only_inputs() -> None:
    assert map_legacy_authority_role("DIRECT_AUTHORITY") is AuthorityRole.GOVERNING
    assert map_legacy_authority_role("IMPLEMENTING_OR_INTERNAL_RULE") is AuthorityRole.IMPLEMENTING
    assert map_legacy_coverage_state("AMBIGUOUS") is CoverageState.CONFLICT
    assert map_legacy_coverage_state("UNAVAILABLE") is CoverageState.UNSUPPORTED


def test_authority_proposal_cannot_assert_verified_applicability() -> None:
    with pytest.raises(ValidationError, match="proposal cannot assert verified applicability"):
        AuthorityCandidate(
            document=_document(),
            role=AuthorityRole.GOVERNING,
            state=AuthorityState.ELIGIBLE,
            applicability=ApplicabilityState.VERIFIED,
        )


def test_create_legal_case_starts_at_received_state() -> None:
    context = create_legal_case("private question")

    assert context.stage is CaseStage.RECEIVED
    assert context.question_analysis is None
    assert context.to_public_dict()["sub_intent_count"] == 0
