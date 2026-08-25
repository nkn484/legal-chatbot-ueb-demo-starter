"""P5 proposal-only relation investigation with deterministic evidence checks."""

from __future__ import annotations

import asyncio
import json

from legal_chatbot.legal_evidence.models import (
    AuthorityCandidate,
    AuthorityRole,
    AuthorityState,
    CaseStage,
    LegalCaseContext,
    RelationHint,
)
from legal_chatbot.legal_evidence.transitions import advance_case, verify_relation
from legal_chatbot.providers.models import GenerationRequest
from legal_chatbot.providers.port import LLMProviderPort

from .models import (
    RelationConflict,
    RelationEvidence,
    RelationHintProposal,
    RelationInvestigationOutcome,
    RelationInvestigationResult,
    RelationInvestigationSettings,
    build_families,
    marker_matches,
)

_ROLE_PRIORITY = {
    AuthorityRole.GOVERNING: 0,
    AuthorityRole.IMPLEMENTING: 1,
    AuthorityRole.SUPPLEMENTARY: 2,
    AuthorityRole.BACKGROUND: 3,
    AuthorityRole.IRRELEVANT: 4,
}
_APPLICABILITY_PRIORITY = {
    "METADATA_CURRENT": 0,
    "CURRENT_EFFECT_UNVERIFIED": 1,
    "UNKNOWN": 2,
    "CONFLICT": 3,
    "VERIFIED": 0,
}


class RelationInvestigationService:
    def __init__(
        self,
        provider: LLMProviderPort | None,
        settings: RelationInvestigationSettings | None = None,
    ) -> None:
        self._provider = provider
        self._settings = settings or RelationInvestigationSettings()

    async def investigate(
        self,
        candidates: tuple[AuthorityCandidate, ...],
        evidence: tuple[RelationEvidence, ...] = (),
    ) -> RelationInvestigationResult:
        allowed = tuple(
            candidate
            for candidate in candidates
            if candidate.state is AuthorityState.ELIGIBLE
            and candidate.role is not AuthorityRole.IRRELEVANT
        )[:15]
        hints, outcome = await self._hints(allowed)
        evidence_by_hint = {item.hint_id: item for item in evidence}
        verified = tuple(
            verify_relation(hint, evidence_by_hint[hint.relation_id].evidence)
            for hint in hints
            if hint.relation_id in evidence_by_hint
            and marker_matches(evidence_by_hint[hint.relation_id].marker, hint.relation_type)
        )
        return RelationInvestigationResult(
            families=build_families(allowed, verified),
            hints=hints,
            verified=verified,
            conflicts=self._conflicts(verified),
            retained_document_version_ids=tuple(
                item.document.document_version_id for item in allowed
            ),
            outcome=outcome,
        )

    async def investigate_context(
        self,
        context: LegalCaseContext,
        evidence: tuple[RelationEvidence, ...] = (),
    ) -> RelationContextResult:
        """Advance P5 only from the complete authority classification held by P4."""

        if context.stage is not CaseStage.AUTHORITY_REVIEWED:
            raise ValueError("relation investigation requires authority-reviewed context")
        candidate_versions = {
            candidate.document.document_version_id for candidate in context.candidate_documents
        }
        if not context.authority_candidates or any(
            candidate.document.document_version_id not in candidate_versions
            for candidate in context.authority_candidates
        ):
            raise ValueError("P5 requires complete P4 authority candidates")
        selected, pruned = self._prioritize_for_context(context)
        result = await self.investigate(selected, evidence)
        result = result.model_copy(
            update={
                "retained_document_version_ids": tuple(
                    item.document.document_version_id for item in selected
                ),
                "budget_pruned_document_version_ids": tuple(
                    item.document.document_version_id for item in pruned
                ),
            }
        )
        updated = advance_case(
            context,
            CaseStage.FAMILIES_RESOLVED,
            authority_families=result.families,
            relation_hints=result.hints,
            verified_relations=result.verified,
        )
        return RelationContextResult(context=updated, result=result)

    @staticmethod
    def _prioritize_for_context(context: LegalCaseContext):
        """Select up to fifteen candidate families by coverage and role, never source ID."""

        candidates = tuple(
            candidate
            for candidate in context.authority_candidates
            if candidate.state is AuthorityState.ELIGIBLE
            and candidate.role is not AuthorityRole.IRRELEVANT
        )
        assessments = {
            (item.document.document_version_id, item.sub_intent_id): item
            for item in context.authority_assessments
            if item.state is AuthorityState.ELIGIBLE
            and item.role is not AuthorityRole.IRRELEVANT
        }
        if not assessments:
            return candidates[:15], candidates[15:]
        source_order = {
            candidate.document.document_version_id: index
            for index, candidate in enumerate(candidates)
        }

        def scored(candidate: AuthorityCandidate):
            version_id = candidate.document.document_version_id
            related = [
                assessment
                for (assessment_version, _), assessment in assessments.items()
                if assessment_version == version_id
            ]
            best_role = min(_ROLE_PRIORITY[item.role] for item in related)
            best_applicability = min(
                _APPLICABILITY_PRIORITY[item.applicability.value] for item in related
            )
            return (best_role, -len(related), best_applicability, source_order[version_id])

        selected: list[AuthorityCandidate] = []
        selected_versions: set[object] = set()
        for sub_intent in context.sub_intents:
            options = [
                candidate
                for candidate in candidates
                if (candidate.document.document_version_id, sub_intent.sub_intent_id) in assessments
            ]
            if options:
                chosen = min(options, key=scored)
                if chosen.document.document_version_id not in selected_versions:
                    selected.append(chosen)
                    selected_versions.add(chosen.document.document_version_id)
        for candidate in sorted(candidates, key=scored):
            if len(selected) >= 15:
                break
            if candidate.document.document_version_id not in selected_versions:
                selected.append(candidate)
                selected_versions.add(candidate.document.document_version_id)
        selected_set = {item.document.document_version_id for item in selected}
        return tuple(selected), tuple(
            item for item in candidates if item.document.document_version_id not in selected_set
        )

    async def _hints(self, candidates: tuple[AuthorityCandidate, ...]):
        if not self._settings.enabled:
            return (), RelationInvestigationOutcome.DISABLED_FALLBACK
        if self._provider is None:
            return (), RelationInvestigationOutcome.PROVIDER_FAILURE_FALLBACK
        prompt = (
            "Propose relation hints only. Return JSON with one hints array. "
            f"Candidate indices are 0 through {len(candidates) - 1}."
        )
        try:
            generated = await asyncio.wait_for(
                self._provider.generate(
                    GenerationRequest(
                        input_text=prompt, max_output_tokens=self._settings.max_output_tokens
                    )
                ),
                timeout=self._settings.timeout_seconds,
            )
            value = json.loads(generated.text)
            if (
                not isinstance(value, dict)
                or set(value) != {"hints"}
                or not isinstance(value["hints"], list)
            ):
                raise ValueError
            proposals = tuple(RelationHintProposal.model_validate(item) for item in value["hints"])
            if any(
                item.subject_index >= len(candidates) or item.object_index >= len(candidates)
                for item in proposals
            ):
                raise ValueError
            hints = tuple(
                RelationHint(
                    subject_document_version_id=candidates[
                        item.subject_index
                    ].document.document_version_id,
                    object_document_version_id=candidates[
                        item.object_index
                    ].document.document_version_id,
                    relation_type=item.relation_type,
                )
                for item in proposals
            )
            return hints, RelationInvestigationOutcome.LLM_HINTS
        except ValueError:
            return (), RelationInvestigationOutcome.INVALID_OUTPUT_FALLBACK
        except Exception:
            return (), RelationInvestigationOutcome.PROVIDER_FAILURE_FALLBACK

    @staticmethod
    def _conflicts(verified):
        grouped = {}
        for relation in verified:
            key = (relation.subject_document_version_id, relation.object_document_version_id)
            grouped.setdefault(key, set()).add(relation.relation_type)
        return tuple(
            RelationConflict(
                subject_document_version_id=key[0],
                object_document_version_id=key[1],
                relation_types=tuple(sorted(types, key=lambda value: value.value)),
            )
            for key, types in grouped.items()
            if len(types) > 1
        )


class RelationContextResult:
    """P5 result coupled to its immutable request-state transition."""

    def __init__(self, *, context: LegalCaseContext, result: RelationInvestigationResult) -> None:
        self.context = context
        self.result = result

    @property
    def families(self):
        return self.result.families

    @property
    def outcome(self):
        return self.result.outcome


__all__ = ["RelationContextResult", "RelationInvestigationService"]
