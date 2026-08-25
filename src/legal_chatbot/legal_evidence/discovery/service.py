"""Pure orchestration for P3 broad discovery before authority selection."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Protocol

from legal_chatbot.legal_evidence.models import (
    AuthorityState,
    CandidateDocument,
    CaseStage,
    LegalCaseContext,
)
from legal_chatbot.legal_evidence.transitions import advance_case

from .models import (
    BroadDiscoveryWorkspace,
    DiscoveryDocument,
    DiscoveryLaneObservation,
    DiscoveryOutcome,
    DiscoveryReadRequest,
    DiscoverySettings,
    RawDiscoveryCandidate,
)


class BroadDiscoveryReaderPort(Protocol):
    """Read independent discovery-lane candidates without making final evidence decisions."""

    async def discover(self, request: DiscoveryReadRequest) -> tuple[RawDiscoveryCandidate, ...]:
        """Return bounded raw candidates for one material sub-intent."""
        ...


class BroadDiscoveryResult:
    """Immutable P3 output kept separate from authority and evidence-selection stages."""

    def __init__(
        self,
        *,
        context: LegalCaseContext,
        workspace: BroadDiscoveryWorkspace,
        outcome: DiscoveryOutcome,
    ) -> None:
        self.context = context
        self.workspace = workspace
        self.outcome = outcome

    def to_public_dict(self) -> dict[str, object]:
        return {"outcome": self.outcome.value, "workspace": self.workspace.to_public_dict()}


def _best_observation(
    current: DiscoveryLaneObservation | None, candidate: DiscoveryLaneObservation
) -> DiscoveryLaneObservation:
    if current is None:
        return candidate
    current_score = current.score if current.score is not None else float("-inf")
    candidate_score = candidate.score if candidate.score is not None else float("-inf")
    if (candidate.rank, -candidate_score) < (current.rank, -current_score):
        return candidate
    return current


def collapse_candidates(
    candidates: tuple[RawDiscoveryCandidate, ...], *, workspace_limit: int
) -> BroadDiscoveryWorkspace:
    """Collapse by full immutable identity before spending the workspace budget."""

    grouped: dict[object, list[RawDiscoveryCandidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.document].append(candidate)
    collapsed: list[DiscoveryDocument] = []
    provenance_filtered_count = 0
    for document, group in grouped.items():
        states = {item.state for item in group}
        if len(states) != 1:
            raise ValueError("same identity cannot have conflicting discovery states")
        state = states.pop()
        if state is AuthorityState.FILTERED_PROVENANCE:
            provenance_filtered_count += 1
        sub_intent_ids = tuple(
            sorted({item_id for item in group for item_id in item.matched_sub_intent_ids})
        )
        by_lane: dict[object, DiscoveryLaneObservation] = {}
        for item in group:
            for observation in item.observations:
                by_lane[observation.lane] = _best_observation(
                    by_lane.get(observation.lane), observation
                )
        collapsed.append(
            DiscoveryDocument(
                document=document,
                state=state,
                matched_sub_intent_ids=sub_intent_ids,
                observations=tuple(sorted(by_lane.values(), key=lambda value: value.lane.value)),
                supporting_candidate_count=len(group),
            )
        )
    ordered = tuple(
        sorted(
            collapsed,
            key=lambda item: (
                min(observation.rank for observation in item.observations),
                str(item.document.document_version_id),
            ),
        )[:workspace_limit]
    )
    return BroadDiscoveryWorkspace(
        documents=ordered,
        workspace_limit=workspace_limit,
        raw_candidate_count=len(candidates),
        provenance_filtered_count=provenance_filtered_count,
    )


class BroadDiscoveryService:
    """Build a bounded P3 workspace without authority ranking or final selection."""

    def __init__(
        self, reader: BroadDiscoveryReaderPort, settings: DiscoverySettings | None = None
    ) -> None:
        self._reader = reader
        self._settings = settings or DiscoverySettings()

    async def discover(self, context: LegalCaseContext) -> BroadDiscoveryResult:
        if not self._settings.enabled:
            return BroadDiscoveryResult(
                context=context,
                workspace=BroadDiscoveryWorkspace(workspace_limit=self._settings.workspace_limit),
                outcome=DiscoveryOutcome.DISABLED,
            )
        if context.stage is not CaseStage.ANALYZED:
            raise ValueError("broad discovery requires an analyzed legal case")
        requests = tuple(
            DiscoveryReadRequest(
                sub_intent_id=sub_intent.sub_intent_id,
                query_text=" ".join(sub_intent.retrieval_concepts) or sub_intent.description,
            )
            for sub_intent in context.sub_intents
        )
        per_intent = await asyncio.gather(*(self._reader.discover(request) for request in requests))
        raw = tuple(candidate for candidates in per_intent for candidate in candidates)
        workspace = collapse_candidates(raw, workspace_limit=self._settings.workspace_limit)
        updated = advance_case(
            context,
            CaseStage.DISCOVERED,
            candidate_documents=tuple(
                CandidateDocument(
                    document=document.document,
                    state=document.state,
                    matched_sub_intent_ids=document.matched_sub_intent_ids,
                )
                for document in workspace.documents
            ),
        )
        return BroadDiscoveryResult(
            context=updated,
            workspace=workspace,
            outcome=DiscoveryOutcome.COMPLETED,
        )


__all__ = [
    "BroadDiscoveryReaderPort",
    "BroadDiscoveryResult",
    "BroadDiscoveryService",
    "collapse_candidates",
]
