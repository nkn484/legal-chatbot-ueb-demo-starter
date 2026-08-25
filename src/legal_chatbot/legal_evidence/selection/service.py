"""P9 deterministic coverage-first selection without similarity-only cutoff."""

from legal_chatbot.legal_evidence.models import AuthorityRole, CaseStage
from legal_chatbot.legal_evidence.transitions import advance_case

from .models import EvidenceSelectionSettings, FinalEvidenceSelection

_ROLE_ORDER = {
    AuthorityRole.GOVERNING: 0,
    AuthorityRole.IMPLEMENTING: 1,
    AuthorityRole.SUPPLEMENTARY: 2,
    AuthorityRole.BACKGROUND: 3,
    AuthorityRole.IRRELEVANT: 4,
}


class CoverageFirstEvidenceSelector:
    def __init__(self, settings: EvidenceSelectionSettings | None = None) -> None:
        self._settings = settings or EvidenceSelectionSettings()

    def select(self, context) -> FinalEvidenceSelection:
        if not self._settings.enabled:
            return FinalEvidenceSelection(target_count=3)
        if context.stage not in (CaseStage.COVERAGE_REVIEWED, CaseStage.REPAIRED):
            raise ValueError("coverage-first selection requires reviewed coverage")
        target = min(self._settings.max_evidence, max(3, len(context.sub_intents)))
        selected = []
        reasons = []
        used = set()
        for index, sub_intent in enumerate(context.sub_intents, start=1):
            options = [
                unit
                for unit in context.evidence_units
                if sub_intent.sub_intent_id in unit.supported_sub_intent_ids
            ]
            for unit in sorted(options, key=lambda value: _ROLE_ORDER[value.authority_role]):
                if unit.evidence.chunk_id not in used:
                    selected.append(unit)
                    used.add(unit.evidence.chunk_id)
                    reasons.append(
                        f"sub_intent_{index}_role_priority_{unit.authority_role.value}"
                    )
                    break
        for unit in sorted(
            context.evidence_units, key=lambda value: _ROLE_ORDER[value.authority_role]
        ):
            if len(selected) >= target:
                break
            if unit.evidence.chunk_id not in used:
                selected.append(unit)
                used.add(unit.evidence.chunk_id)
                reasons.append(f"additional_eligible_role_priority_{unit.authority_role.value}")
        return FinalEvidenceSelection(
            evidence_units=tuple(selected),
            selection_reasons=tuple(reasons),
            target_count=target,
        )

    def select_context(self, context):
        result = self.select(context)
        if not self._settings.enabled:
            return context, result
        return advance_case(
            context, CaseStage.EVIDENCE_SELECTED, evidence_units=result.evidence_units
        ), result


__all__ = ["CoverageFirstEvidenceSelector"]
