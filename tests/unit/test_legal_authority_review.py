import json
from uuid import uuid4

import pytest

from legal_chatbot.legal_evidence import (
    AnalysisOrigin,
    AuthorityRole,
    AuthorityState,
    CaseStage,
    DocumentVersionReference,
    QuestionAnalysis,
    SubIntent,
    advance_case,
    create_legal_case,
)
from legal_chatbot.legal_evidence.authority import (
    AuthorityMetadata,
    AuthorityReviewOutcome,
    AuthorityReviewService,
    AuthorityReviewSettings,
    validate_authority_candidate,
)
from legal_chatbot.legal_evidence.discovery import (
    BroadDiscoveryResult,
    BroadDiscoveryWorkspace,
    DiscoveryDocument,
    DiscoveryLane,
    DiscoveryLaneObservation,
    DiscoveryOutcome,
)
from legal_chatbot.providers.models import GenerationRequest, GenerationResult


def _document() -> DocumentVersionReference:
    return DocumentVersionReference(
        document_id=uuid4(),
        document_version_id=uuid4(),
        provenance_record_id=uuid4(),
        source_id="VBQPPL",
    )


def _metadata(document: DocumentVersionReference, **updates) -> AuthorityMetadata:
    values = {
        "document": document,
        "discovery_state": AuthorityState.ELIGIBLE,
        "provenance_valid": True,
        "scope_compatible": True,
        "source_binding_compatible": True,
        "status_eligible": True,
        "status_metadata_current": False,
    }
    values.update(updates)
    return AuthorityMetadata(**values)


def _discovery(document: DocumentVersionReference) -> BroadDiscoveryResult:
    context = advance_case(
        create_legal_case("private authority question"),
        CaseStage.ANALYZED,
        question_analysis=QuestionAnalysis(
            origin=AnalysisOrigin.DETERMINISTIC_FALLBACK,
            main_intent="private intent",
        ),
        sub_intents=(SubIntent(description="private issue"),),
    )
    discovered = advance_case(
        context,
        CaseStage.DISCOVERED,
        candidate_documents=(),
    )
    workspace = BroadDiscoveryWorkspace(
        documents=(
            DiscoveryDocument(
                document=document,
                state=AuthorityState.ELIGIBLE,
                matched_sub_intent_ids=(context.sub_intents[0].sub_intent_id,),
                observations=(
                    DiscoveryLaneObservation(
                        lane=DiscoveryLane.SEMANTIC_VECTOR,
                        rank=1,
                        score=1,
                        query_count=1,
                        elapsed_ms=1,
                    ),
                ),
                supporting_candidate_count=1,
            ),
        ),
        workspace_limit=15,
    )
    return BroadDiscoveryResult(
        context=discovered,
        workspace=workspace,
        outcome=DiscoveryOutcome.COMPLETED,
    )


def test_hard_filters_override_governing_proposal_and_preserve_non_retrieval_states() -> None:
    document = _document()
    scope_conflict = validate_authority_candidate(
        _metadata(document, scope_compatible=False), AuthorityRole.GOVERNING, proposal_only=True
    )
    quarantined = validate_authority_candidate(
        _metadata(document, discovery_state=AuthorityState.QUARANTINED),
        AuthorityRole.GOVERNING,
        proposal_only=True,
    )
    not_retrieved = validate_authority_candidate(
        _metadata(document, discovery_state=AuthorityState.NOT_RETRIEVED),
        AuthorityRole.GOVERNING,
        proposal_only=True,
    )

    assert scope_conflict.state is AuthorityState.FILTERED_SCOPE
    assert scope_conflict.role is AuthorityRole.IRRELEVANT
    assert quarantined.state is AuthorityState.QUARANTINED
    assert not_retrieved.state is AuthorityState.NOT_RETRIEVED
    assert quarantined.state is not not_retrieved.state


def test_eligible_governing_proposal_keeps_current_effect_as_soft_qualification() -> None:
    candidate = validate_authority_candidate(
        _metadata(_document(), status_metadata_current=False),
        AuthorityRole.GOVERNING,
        proposal_only=True,
    )

    assert candidate.role is AuthorityRole.GOVERNING
    assert candidate.state is AuthorityState.ELIGIBLE
    assert candidate.applicability.value == "CURRENT_EFFECT_UNVERIFIED"


class _Provider:
    async def generate(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(
            text=json.dumps({"candidates": [{"candidate_index": 0, "role": "GOVERNING"}]}),
            provider="stub",
            model="stub",
            duration_ms=1,
        )

    async def health_check(self):
        raise AssertionError("not used")

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_llm_role_proposal_is_validated_and_default_fallback_remains_safe() -> None:
    document = _document()
    discovery = _discovery(document)
    metadata = (_metadata(document, source_binding_compatible=False),)

    proposed = await AuthorityReviewService(
        _Provider(), AuthorityReviewSettings(enabled=True)
    ).review_context(discovery, metadata)
    fallback = await AuthorityReviewService(None).review(discovery, (_metadata(document),))

    assert proposed.outcome is AuthorityReviewOutcome.LLM_PROPOSALS
    assert proposed.candidates[0].state is AuthorityState.FILTERED_SOURCE_BINDING
    assert proposed.candidates[0].role is AuthorityRole.IRRELEVANT
    assert fallback.outcome is AuthorityReviewOutcome.DISABLED_FALLBACK
    assert fallback.candidates[0].role is AuthorityRole.BACKGROUND
