from types import SimpleNamespace
from uuid import uuid4

from legal_chatbot.legal_evidence import AuthorityRole, CaseStage, EvidenceReference, EvidenceUnit
from legal_chatbot.legal_evidence.selection import (
    CoverageFirstEvidenceSelector,
    EvidenceSelectionSettings,
)


def _unit(sub_id, role):
    evidence = EvidenceReference.model_construct(
        document=SimpleNamespace(), chunk_id=uuid4(), locator="Article 1"
    )
    return EvidenceUnit(evidence=evidence, supported_sub_intent_ids=(sub_id,), authority_role=role)


def test_coverage_first_preserves_each_sub_intent_before_extra_evidence_without_padding():
    first, second, third = uuid4(), uuid4(), uuid4()
    context = SimpleNamespace(
        stage=CaseStage.REPAIRED,
        sub_intents=(
            SimpleNamespace(sub_intent_id=first),
            SimpleNamespace(sub_intent_id=second),
            SimpleNamespace(sub_intent_id=third),
        ),
        evidence_units=(
            _unit(first, AuthorityRole.GOVERNING),
            _unit(first, AuthorityRole.SUPPLEMENTARY),
            _unit(second, AuthorityRole.IMPLEMENTING),
            _unit(third, AuthorityRole.GOVERNING),
        ),
    )
    result = CoverageFirstEvidenceSelector(EvidenceSelectionSettings(enabled=True)).select(context)

    covered = {sub_id for unit in result.evidence_units for sub_id in unit.supported_sub_intent_ids}
    assert {first, second, third} <= covered
    assert len(result.evidence_units) == 3
    assert result.padding_used is False


def test_selector_allows_fewer_than_three_when_eligible_evidence_is_scarce():
    sub_id = uuid4()
    context = SimpleNamespace(
        stage=CaseStage.REPAIRED,
        sub_intents=(SimpleNamespace(sub_intent_id=sub_id),),
        evidence_units=(_unit(sub_id, AuthorityRole.GOVERNING),),
    )
    result = CoverageFirstEvidenceSelector(EvidenceSelectionSettings(enabled=True)).select(context)
    assert len(result.evidence_units) == 1
    assert result.target_count == 3
