from types import SimpleNamespace
from uuid import uuid4

import pytest

from legal_chatbot.legal_evidence import AuthorityRole, CaseStage
from legal_chatbot.legal_evidence.completeness import (
    CompletenessReviewService,
    CompletenessSettings,
    MissingEvidenceCode,
)


def _context():
    first, second, third = uuid4(), uuid4(), uuid4()
    return (
        SimpleNamespace(
            stage=CaseStage.EVIDENCE_READ,
            sub_intents=(
                SimpleNamespace(sub_intent_id=first),
                SimpleNamespace(sub_intent_id=second),
                SimpleNamespace(sub_intent_id=third),
            ),
            evidence_units=(
                SimpleNamespace(
                    supported_sub_intent_ids=(first,), authority_role=AuthorityRole.GOVERNING
                ),
                SimpleNamespace(
                    supported_sub_intent_ids=(second,), authority_role=AuthorityRole.SUPPLEMENTARY
                ),
            ),
        ),
        first,
        second,
        third,
    )


@pytest.mark.asyncio
async def test_completeness_is_per_sub_intent_and_never_promotes_partial_or_missing_evidence() -> (
    None
):
    context, first, second, third = _context()
    result = await CompletenessReviewService(None).review(context)
    by_id = {entry.sub_intent_id: entry for entry in result.entries}

    assert by_id[first].state.value == "SUPPORTED"
    assert by_id[second].state.value == "PARTIALLY_SUPPORTED"
    assert by_id[third].state.value == "UNSUPPORTED"
    assert by_id[second].governing_authority_present is False
    assert MissingEvidenceCode.GOVERNING_AUTHORITY in by_id[second].missing_codes
    assert MissingEvidenceCode.CLAUSE_EVIDENCE in by_id[third].missing_codes


class _Provider:
    async def generate(self, request):
        return SimpleNamespace(text='{"entries":[{"sub_intent_index":1,"missing_codes":[]}]}')


@pytest.mark.asyncio
async def test_reviewer_proposal_cannot_change_deterministic_coverage_state() -> None:
    context, _, second, _ = _context()
    result = await CompletenessReviewService(
        _Provider(), CompletenessSettings(enabled=True)
    ).review(context)
    partial = next(entry for entry in result.entries if entry.sub_intent_id == second)

    assert partial.state.value == "PARTIALLY_SUPPORTED"
    assert result.reviewer_used is True
