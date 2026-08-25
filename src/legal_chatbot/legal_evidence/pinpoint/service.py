"""P6 pinpoint reader orchestration without broad-corpus fallback or evidence padding."""

from __future__ import annotations

import asyncio
from typing import Protocol
from uuid import UUID

from legal_chatbot.legal_evidence.models import (
    AuthorityRole,
    AuthorityState,
    CaseStage,
    EvidenceUnit,
    LegalCaseContext,
)
from legal_chatbot.legal_evidence.transitions import advance_case

from .models import (
    PinpointEvidenceResult,
    PinpointOutcome,
    PinpointReadRequest,
    PinpointSettings,
    RawPinpointEvidence,
)
from .query import build_pinpoint_query


class PinpointEvidenceReaderPort(Protocol):
    async def read(self, request: PinpointReadRequest) -> tuple[RawPinpointEvidence, ...]: ...


class PinpointContextResult:
    def __init__(self, context: LegalCaseContext, result: PinpointEvidenceResult) -> None:
        self.context = context
        self.result = result


class PinpointEvidenceService:
    def __init__(
        self, reader: PinpointEvidenceReaderPort, settings: PinpointSettings | None = None
    ) -> None:
        self._reader = reader
        self._settings = settings or PinpointSettings()

    async def read(self, context: LegalCaseContext) -> PinpointEvidenceResult:
        if not self._settings.enabled:
            return PinpointEvidenceResult(outcome=PinpointOutcome.DISABLED)
        if context.stage is not CaseStage.FAMILIES_RESOLVED:
            raise ValueError("pinpoint evidence reading requires resolved authority families")
        eligible_authorities = {
            item.document.document_version_id: item
            for item in context.authority_candidates
            if item.state is AuthorityState.ELIGIBLE
            and item.role is not AuthorityRole.IRRELEVANT
        }
        family_versions = {
            version
            for family in context.authority_families
            for version in family.document_version_ids
        }
        if not family_versions:
            return PinpointEvidenceResult(outcome=PinpointOutcome.NO_ELIGIBLE_FAMILY)
        if not family_versions <= set(eligible_authorities):
            raise ValueError("P6 requires eligible P5 authority-family state")
        assessment_roles = {
            (item.document.document_version_id, item.sub_intent_id): item.role
            for item in context.authority_assessments
            if item.state is AuthorityState.ELIGIBLE
            and item.role is not AuthorityRole.IRRELEVANT
        }
        requests = []
        request_roles: dict[object, dict[object, AuthorityRole]] = {}
        for sub_intent in context.sub_intents:
            if context.authority_assessments:
                scoped = {
                    version
                    for version in family_versions
                    if (version, sub_intent.sub_intent_id) in assessment_roles
                }
            else:
                scoped = {
                    candidate.document.document_version_id
                    for candidate in context.candidate_documents
                    if sub_intent.sub_intent_id in candidate.matched_sub_intent_ids
                } & family_versions
            allowed = tuple(sorted(scoped, key=str))
            if allowed:
                documents = tuple(eligible_authorities[version].document for version in allowed)
                request = PinpointReadRequest(
                    sub_intent_id=sub_intent.sub_intent_id,
                    document_version_ids=allowed,
                    documents=documents,
                    query_text=build_pinpoint_query(sub_intent),
                )
                requests.append(request)
                request_roles[sub_intent.sub_intent_id] = {
                    version: assessment_roles.get(
                        (version, sub_intent.sub_intent_id), eligible_authorities[version].role
                    )
                    for version in allowed
                }
        reads = await asyncio.gather(*(self._reader.read(request) for request in requests))
        units: list[EvidenceUnit] = []
        for request, raw_items in zip(requests, reads, strict=True):
            allowed = set(request.document_version_ids)
            seen_chunks: set[UUID] = set()
            for item in sorted(raw_items, key=lambda value: value.rank):
                if item.sub_intent_id != request.sub_intent_id:
                    raise ValueError("pinpoint evidence sub-intent does not match request")
                if item.evidence.document.document_version_id not in allowed:
                    raise ValueError("pinpoint evidence is outside the selected authority family")
                if item.evidence.chunk_id in seen_chunks:
                    continue
                seen_chunks.add(item.evidence.chunk_id)
                units.append(
                    EvidenceUnit(
                        evidence=item.evidence,
                        supported_sub_intent_ids=(request.sub_intent_id,),
                        authority_role=request_roles[request.sub_intent_id][
                            item.evidence.document.document_version_id
                        ],
                    )
                )
                if len(seen_chunks) >= self._settings.max_evidence_per_sub_intent:
                    break
        return PinpointEvidenceResult(
            evidence_units=tuple(units), outcome=PinpointOutcome.COMPLETED
        )

    async def read_context(self, context: LegalCaseContext) -> PinpointContextResult:
        result = await self.read(context)
        if result.outcome is PinpointOutcome.DISABLED:
            return PinpointContextResult(context, result)
        updated = advance_case(
            context, CaseStage.EVIDENCE_READ, evidence_units=result.evidence_units
        )
        return PinpointContextResult(updated, result)


__all__ = ["PinpointContextResult", "PinpointEvidenceReaderPort", "PinpointEvidenceService"]
