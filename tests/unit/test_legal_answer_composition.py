from types import SimpleNamespace
from uuid import uuid4

import pytest

from legal_chatbot.legal_evidence import AuthorityRole, CaseStage, EvidenceReference, EvidenceUnit
from legal_chatbot.legal_evidence.composition import (
    CompositionEvidence,
    CompositionSettings,
    StructuredAnswerComposer,
)
from legal_chatbot.providers.models import GenerationResult


def _unit():
    evidence = EvidenceReference.model_construct(
        document=SimpleNamespace(), chunk_id=uuid4(), locator="Article 1"
    )
    return EvidenceUnit(
        evidence=evidence,
        supported_sub_intent_ids=(uuid4(),),
        authority_role=AuthorityRole.GOVERNING,
    )


class _Reader:
    def __init__(self, unit):
        self.unit = unit

    async def load(self, units):
        return (CompositionEvidence(unit=self.unit, excerpt="private evidence"),)


class _Provider:
    async def generate(self, request):
        return GenerationResult(
            text=(
                '{"answer":"bounded answer","claims":['
                '{"claim_index":0,"kind":"SOURCE_FACT",'
                '"sub_intent_indices":[0],"evidence_indices":[0]}]}'
            ),
            provider="stub",
            model="stub",
            duration_ms=1,
        )


@pytest.mark.asyncio
async def test_composer_is_default_off_and_enabled_claims_must_reference_pack():
    unit = _unit()
    context = SimpleNamespace(
        stage=CaseStage.EVIDENCE_SELECTED, evidence_units=(unit,), sub_intents=(SimpleNamespace(),)
    )
    disabled = await StructuredAnswerComposer(None, _Reader(unit)).compose(context)
    enabled = await StructuredAnswerComposer(
        _Provider(), _Reader(unit), CompositionSettings(enabled=True)
    ).compose(context)
    assert disabled.enabled is False
    assert enabled.enabled is True
    assert enabled.claims[0].evidence_indices == (0,)


@pytest.mark.asyncio
async def test_composer_rejects_evidence_reader_drift():
    unit = _unit()
    context = SimpleNamespace(
        stage=CaseStage.EVIDENCE_SELECTED, evidence_units=(unit,), sub_intents=(SimpleNamespace(),)
    )
    other = _unit()
    with pytest.raises(ValueError, match="exactly"):
        await StructuredAnswerComposer(
            _Provider(), _Reader(other), CompositionSettings(enabled=True)
        ).compose(context)
