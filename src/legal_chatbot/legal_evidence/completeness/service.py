"""P7 deterministic per-sub-intent completeness with non-promoting reviewer hints."""

from __future__ import annotations

import asyncio
import json

from legal_chatbot.legal_evidence.models import (
    ApplicabilityState,
    AuthorityRole,
    CaseStage,
    CoverageEntry,
    CoverageMatrix,
    CoverageState,
)
from legal_chatbot.legal_evidence.transitions import advance_case
from legal_chatbot.providers.models import GenerationRequest
from legal_chatbot.providers.port import LLMProviderPort

from .models import (
    CompletenessEntry,
    CompletenessProposal,
    CompletenessResult,
    CompletenessSettings,
    MissingEvidenceCode,
)


class CompletenessReviewService:
    def __init__(
        self, provider: LLMProviderPort | None, settings: CompletenessSettings | None = None
    ) -> None:
        self._provider = provider
        self._settings = settings or CompletenessSettings()

    async def review(self, context) -> CompletenessResult:
        if context.stage not in (CaseStage.EVIDENCE_READ, CaseStage.REPAIRED):
            raise ValueError("completeness review requires pinpoint evidence")
        entries = tuple(
            self._deterministic_entry(context, sub_intent.sub_intent_id)
            for sub_intent in context.sub_intents
        )
        proposals, used = await self._proposals(len(entries))
        proposal_codes = {item.sub_intent_index: item.missing_codes for item in proposals}
        merged_entries = []
        for index, entry in enumerate(entries):
            codes = tuple(dict.fromkeys((*entry.missing_codes, *proposal_codes.get(index, ()))))
            merged_entries.append(entry.model_copy(update={"missing_codes": codes}))
        merged = tuple(merged_entries)
        return CompletenessResult(entries=merged, reviewer_used=used)

    async def review_context(self, context):
        result = await self.review(context)
        matrix = CoverageMatrix(
            entries=tuple(
                CoverageEntry(
                    sub_intent_id=entry.sub_intent_id,
                    state=entry.state,
                    governing_authority_present=entry.governing_authority_present,
                    applicability=entry.applicability,
                )
                for entry in result.entries
            )
        )
        if context.stage is CaseStage.REPAIRED:
            return context.model_copy(update={"coverage_matrix": matrix}), result
        return advance_case(context, CaseStage.COVERAGE_REVIEWED, coverage_matrix=matrix), result

    @staticmethod
    def _deterministic_entry(context, sub_intent_id):
        units = [
            unit
            for unit in context.evidence_units
            if sub_intent_id in unit.supported_sub_intent_ids
        ]
        roles = {unit.authority_role for unit in units}
        governing = AuthorityRole.GOVERNING in roles
        implementing = AuthorityRole.IMPLEMENTING in roles
        if not units:
            state = CoverageState.UNSUPPORTED
        elif governing:
            state = CoverageState.SUPPORTED
        else:
            state = CoverageState.PARTIALLY_SUPPORTED
        missing = []
        if not governing:
            missing.append(MissingEvidenceCode.GOVERNING_AUTHORITY)
        if units and not implementing:
            missing.append(MissingEvidenceCode.IMPLEMENTING_AUTHORITY)
        if not units:
            missing.append(MissingEvidenceCode.CLAUSE_EVIDENCE)
        applicability = ApplicabilityState.CURRENT_EFFECT_UNVERIFIED
        return CompletenessEntry(
            sub_intent_id=sub_intent_id,
            state=state,
            governing_authority_present=governing,
            implementing_authority_needed=bool(units),
            implementing_authority_present=implementing,
            applicability=applicability,
            missing_codes=tuple(missing),
        )

    async def _proposals(self, count: int):
        if not self._settings.enabled or self._provider is None:
            return (), False
        try:
            generated = await asyncio.wait_for(
                self._provider.generate(
                    GenerationRequest(
                        input_text=f"Return JSON missing codes for {count} issues.",
                        max_output_tokens=self._settings.max_output_tokens,
                    )
                ),
                timeout=self._settings.timeout_seconds,
            )
            value = json.loads(generated.text)
            if (
                not isinstance(value, dict)
                or set(value) != {"entries"}
                or not isinstance(value["entries"], list)
            ):
                raise ValueError
            proposals = tuple(
                CompletenessProposal.model_validate(item) for item in value["entries"]
            )
            if any(item.sub_intent_index >= count for item in proposals):
                raise ValueError
            return proposals, True
        except Exception:
            return (), False


__all__ = ["CompletenessReviewService"]
