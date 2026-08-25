"""Evidence-bound P10 fallback used only by the vertical-slice integration profile."""

from __future__ import annotations

from legal_chatbot.legal_evidence.models import AnswerDraft, CaseStage
from legal_chatbot.legal_evidence.transitions import advance_case

from .models import AnswerClaim, ClaimKind, CompositionEvidence, CompositionResult
from .service import CompositionEvidenceReaderPort


class DeterministicEvidenceBoundComposer:
    """Produce a bounded raw diagnostic draft without asserting unstated legal conclusions."""

    def __init__(self, reader: CompositionEvidenceReaderPort) -> None:
        self._reader = reader

    async def compose(self, context) -> CompositionResult:
        if context.stage is not CaseStage.EVIDENCE_SELECTED:
            raise ValueError("composition requires selected evidence")
        evidence = tuple(await self._reader.load(context.evidence_units))
        if tuple(item.unit for item in evidence) != context.evidence_units:
            raise ValueError("composition evidence must match selected evidence exactly")
        answer = self._answer(context, evidence)
        claims = tuple(
            AnswerClaim(
                claim_index=index,
                kind=ClaimKind.LIMITATION,
                sub_intent_indices=(index,),
                evidence_indices=tuple(
                    evidence_index
                    for evidence_index, item in enumerate(evidence)
                    if sub_intent.sub_intent_id in item.unit.supported_sub_intent_ids
                ),
            )
            for index, sub_intent in enumerate(context.sub_intents)
        )
        return CompositionResult(answer=answer, claims=claims, enabled=True)

    async def compose_context(self, context):
        result = await self.compose(context)
        return advance_case(
            context, CaseStage.ANSWER_DRAFTED, answer_draft=AnswerDraft(text=result.answer or "")
        ), result

    @staticmethod
    def _answer(context, evidence: tuple[CompositionEvidence, ...]) -> str:
        coverage = {
            entry.sub_intent_id: entry.state.value for entry in context.coverage_matrix.entries
        }
        lines = ["Evidence-bound diagnostic draft"]
        for index, sub_intent in enumerate(context.sub_intents, start=1):
            supporting = [
                item.unit
                for item in evidence
                if sub_intent.sub_intent_id in item.unit.supported_sub_intent_ids
            ]
            locators = ", ".join(item.evidence.locator for item in supporting) or "none"
            lines.append(
                f"Issue {index}: coverage={coverage[sub_intent.sub_intent_id]}; "
                f"selected evidence locators={locators}."
            )
        lines.append(
            "Limitations: this draft reports only retrieved evidence and retained coverage gaps."
        )
        return " ".join(lines)


__all__ = ["DeterministicEvidenceBoundComposer"]
