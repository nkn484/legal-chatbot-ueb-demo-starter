"""P8 bounded repair with no replay, loop, or catalog/quarantine recovery."""

from typing import Protocol

from legal_chatbot.legal_evidence.models import (
    AuthorityRole,
    AuthorityState,
    CaseStage,
    CoverageState,
)
from legal_chatbot.legal_evidence.transitions import advance_case

from .models import RepairOutcome, RepairResult, RepairSettings, TargetedRepairRequest


class TargetedRepairReaderPort(Protocol):
    async def repair(self, request: TargetedRepairRequest): ...


class TargetedRepairService:
    def __init__(
        self, reader: TargetedRepairReaderPort, settings: RepairSettings | None = None
    ) -> None:
        self._reader = reader
        self._settings = settings or RepairSettings()

    async def repair(self, context) -> RepairResult:
        if not self._settings.enabled:
            return RepairResult(outcome=RepairOutcome.DISABLED)
        if context.stage is not CaseStage.COVERAGE_REVIEWED or context.repair_count:
            return RepairResult(outcome=RepairOutcome.NO_TARGET)
        target = next(
            (
                entry
                for entry in context.coverage_matrix.entries
                if entry.state in (CoverageState.PARTIALLY_SUPPORTED, CoverageState.UNSUPPORTED)
            ),
            None,
        )
        if target is None:
            return RepairResult(outcome=RepairOutcome.NO_TARGET)
        states = {
            candidate.state
            for candidate in context.candidate_documents
            if target.sub_intent_id in candidate.matched_sub_intent_ids
        }
        if AuthorityState.NOT_IN_CATALOG in states:
            return RepairResult(outcome=RepairOutcome.NOT_IN_CATALOG)
        if AuthorityState.QUARANTINED in states:
            return RepairResult(outcome=RepairOutcome.QUARANTINED)
        sub_intent = next(
            item for item in context.sub_intents if item.sub_intent_id == target.sub_intent_id
        )
        assessments = getattr(context, "authority_assessments", ())
        assessment_roles = {
            item.document.document_version_id: item.role
            for item in assessments
            if item.sub_intent_id == target.sub_intent_id
            and item.state is AuthorityState.ELIGIBLE
            and item.role is not AuthorityRole.IRRELEVANT
        }
        documents = tuple(
            candidate.document
            for candidate in context.authority_candidates
            if candidate.state is AuthorityState.ELIGIBLE
            and candidate.role is not AuthorityRole.IRRELEVANT
            and (
                not assessments
                or candidate.document.document_version_id in assessment_roles
            )
            and target.sub_intent_id in candidate.matched_sub_intent_ids
        )
        if not documents:
            return RepairResult(outcome=RepairOutcome.NO_TARGET)
        request = TargetedRepairRequest(
            sub_intent_id=target.sub_intent_id,
            missing_role=AuthorityRole.GOVERNING,
            documents=documents,
            authority_roles=tuple(
                assessment_roles.get(candidate.document.document_version_id, candidate.role)
                for candidate in context.authority_candidates
                if candidate.state is AuthorityState.ELIGIBLE
                and candidate.role is not AuthorityRole.IRRELEVANT
                and (
                    not assessments
                    or candidate.document.document_version_id in assessment_roles
                )
                and target.sub_intent_id in candidate.matched_sub_intent_ids
            ),
            query_text=" ".join(sub_intent.retrieval_concepts) or sub_intent.description,
        )
        units = tuple(await self._reader.repair(request))
        if any(target.sub_intent_id not in unit.supported_sub_intent_ids for unit in units):
            raise ValueError("repair evidence must target the recorded sub-intent")
        return RepairResult(
            outcome=RepairOutcome.EXECUTED,
            evidence_units=units[:5],
            repair_executed=True,
            target_sub_intent_id=target.sub_intent_id,
            missing_role=AuthorityRole.GOVERNING,
        )

    async def repair_context(self, context):
        result = await self.repair(context)
        if not result.repair_executed:
            # A clean P8 stop is still a completed repair phase for the sequential context.
            return advance_case(context, CaseStage.REPAIRED), result
        evidence = tuple((*context.evidence_units, *result.evidence_units))
        return advance_case(
            context,
            CaseStage.REPAIRED,
            evidence_units=evidence,
            repair_count=1,
        ), result


__all__ = ["TargetedRepairReaderPort", "TargetedRepairService"]
