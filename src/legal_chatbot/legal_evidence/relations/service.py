"""P5 proposal-only relation investigation with deterministic evidence checks."""

from __future__ import annotations

import asyncio
import json

from legal_chatbot.legal_evidence.models import AuthorityCandidate, RelationHint
from legal_chatbot.legal_evidence.transitions import verify_relation
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
        hints, outcome = await self._hints(candidates)
        evidence_by_hint = {item.hint_id: item for item in evidence}
        verified = tuple(
            verify_relation(hint, evidence_by_hint[hint.relation_id].evidence)
            for hint in hints
            if hint.relation_id in evidence_by_hint
            and marker_matches(evidence_by_hint[hint.relation_id].marker, hint.relation_type)
        )
        return RelationInvestigationResult(
            families=build_families(candidates, verified),
            hints=hints,
            verified=verified,
            conflicts=self._conflicts(verified),
            outcome=outcome,
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


__all__ = ["RelationInvestigationService"]
