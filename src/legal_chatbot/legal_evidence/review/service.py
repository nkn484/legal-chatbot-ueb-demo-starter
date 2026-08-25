"""P11 independent review, bounded same-evidence rewrite, and deterministic guard."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol

from legal_chatbot.legal_evidence.composition.models import (
    AnswerClaim,
    ClaimKind,
    CompositionEvidence,
    CompositionResult,
)
from legal_chatbot.legal_evidence.models import (
    AnswerDraft,
    CaseStage,
    CoverageState,
    ReviewDecision,
    ReviewResult,
)
from legal_chatbot.legal_evidence.transitions import advance_case
from legal_chatbot.providers.models import (
    GenerationRequest,
    OutputVerbosity,
    ReasoningEffort,
    StructuredOutputFormat,
)
from legal_chatbot.providers.port import LLMProviderPort

from .models import (
    P11GuardOutcome,
    P11ReviewContextResult,
    P11ReviewResult,
    ReviewerExecutionOutcome,
    ReviewFinding,
    ReviewFindingCode,
    ReviewSettings,
)
from .parser import StrictLegalAnswerReviewParser
from .prompt import build_reviewer_prompt, build_rewrite_prompt
from .release_guard import DeterministicReviewReleaseGuard, evidence_identity


class ReviewEvidenceReaderPort(Protocol):
    """Load the exact P9-selected evidence, in its original order, without retrieval."""

    async def load(self, evidence_units) -> tuple[CompositionEvidence, ...]: ...


class DraftRewriterPort(Protocol):
    """Rewrite a draft only from the exact P11 evidence pack and bounded findings."""

    async def rewrite(
        self,
        context,
        draft: CompositionResult,
        evidence: tuple[CompositionEvidence, ...],
        findings: tuple[ReviewFinding, ...],
    ) -> CompositionResult: ...


class EvidenceBoundDraftRewriter:
    """Optional one-shot LLM rewriter that has no retrieval or external evidence access."""

    def __init__(self, provider: LLMProviderPort, settings: ReviewSettings | None = None) -> None:
        self._provider = provider
        self._settings = settings or ReviewSettings()

    async def rewrite(
        self,
        context,
        draft: CompositionResult,
        evidence: tuple[CompositionEvidence, ...],
        findings: tuple[ReviewFinding, ...],
    ) -> CompositionResult:
        generated = await asyncio.wait_for(
            self._provider.generate(
                GenerationRequest(
                    input_text=build_rewrite_prompt(context, draft, evidence, findings),
                    max_output_tokens=self._settings.rewrite_max_output_tokens,
                    structured_output=_composition_output_format(),
                    reasoning_effort=ReasoningEffort.MINIMAL,
                    verbosity=OutputVerbosity.LOW,
                )
            ),
            timeout=self._settings.timeout_seconds,
        )
        if generated.finish_reason in {"length", "max_output_tokens"}:
            raise ValueError("P11_REWRITE_OUTPUT_TRUNCATED")
        return _parse_composition_result(generated.text)


class LegalAnswerReviewService:
    """Review P10 claims before P12; P11 itself never authorizes legal release."""

    def __init__(
        self,
        provider: LLMProviderPort | None,
        evidence_reader: ReviewEvidenceReaderPort,
        *,
        rewriter: DraftRewriterPort | None = None,
        settings: ReviewSettings | None = None,
        parser: StrictLegalAnswerReviewParser | None = None,
        guard: DeterministicReviewReleaseGuard | None = None,
    ) -> None:
        self._provider = provider
        self._evidence_reader = evidence_reader
        self._rewriter = rewriter
        self._settings = settings or ReviewSettings()
        self._parser = parser or StrictLegalAnswerReviewParser()
        self._guard = guard or DeterministicReviewReleaseGuard()

    async def review_context(self, context, draft: CompositionResult) -> P11ReviewContextResult:
        """Advance a P10 draft through P11, with no retrieval, registry, or DB writes."""

        if context.stage is not CaseStage.ANSWER_DRAFTED or context.answer_draft is None:
            raise ValueError("P11 review requires an answer draft")
        if not self._settings.enabled:
            return P11ReviewContextResult(
                context=context,
                composition=draft,
                result=P11ReviewResult(
                    reviewer_execution=ReviewerExecutionOutcome.DISABLED,
                    reviewer_pass_count=0,
                    rewrite_count=0,
                    guard_outcome=P11GuardOutcome.DISABLED_NOT_RELEASABLE,
                    evidence_identity_preserved=True,
                ),
            )

        selected_identity = evidence_identity(context.evidence_units)
        try:
            evidence = tuple(await self._evidence_reader.load(context.evidence_units))
            if tuple(item.unit for item in evidence) != context.evidence_units:
                raise ValueError
        except Exception:
            return self._finalize(
                context,
                draft,
                decision=ReviewDecision.BLOCK,
                findings=(ReviewFinding(code=ReviewFindingCode.EVIDENCE_PACK_DRIFT),),
                reviewer_execution=ReviewerExecutionOutcome.PROVIDER_FAILURE,
                reviewer_pass_count=0,
                rewrite_count=0,
                evidence_identity_preserved=False,
            )

        initial_guard = self._guard.assess(
            context, draft, selected_evidence_identity=selected_identity
        )
        proposal, execution = await self._review_once(context, draft, evidence)
        if proposal is None:
            return self._finalize(
                context,
                draft,
                decision=self._fallback_decision(context, initial_guard.findings),
                findings=_merge_findings(
                    initial_guard.findings,
                    (
                        ReviewFinding(
                            code=(
                                ReviewFindingCode.REVIEWER_OUTPUT_INVALID
                                if execution is ReviewerExecutionOutcome.INVALID_OUTPUT
                                else ReviewFindingCode.REVIEWER_UNAVAILABLE
                            )
                        ),
                    ),
                ),
                reviewer_execution=execution,
                reviewer_pass_count=0,
                rewrite_count=0,
                evidence_identity_preserved=initial_guard.evidence_identity_preserved,
            )

        findings = _merge_findings(initial_guard.findings, proposal.findings)
        decision = proposal.decision
        if initial_guard.findings and decision is ReviewDecision.PASS:
            decision = ReviewDecision.REVISE
        if _has_fatal_guard_failure(initial_guard.findings):
            return self._finalize(
                context,
                draft,
                decision=ReviewDecision.BLOCK,
                findings=findings,
                reviewer_execution=execution,
                reviewer_pass_count=1,
                rewrite_count=0,
                evidence_identity_preserved=initial_guard.evidence_identity_preserved,
            )
        if decision is not ReviewDecision.REVISE:
            return self._finalize(
                context,
                draft,
                decision=decision,
                findings=findings,
                reviewer_execution=execution,
                reviewer_pass_count=1,
                rewrite_count=0,
                evidence_identity_preserved=initial_guard.evidence_identity_preserved,
            )
        if self._rewriter is None or self._settings.max_rewrites == 0:
            return self._finalize(
                context,
                draft,
                decision=self._fallback_decision(context, findings),
                findings=_merge_findings(
                    findings, (ReviewFinding(code=ReviewFindingCode.REWRITE_UNAVAILABLE),)
                ),
                reviewer_execution=execution,
                reviewer_pass_count=1,
                rewrite_count=0,
                evidence_identity_preserved=initial_guard.evidence_identity_preserved,
            )

        try:
            rewritten = await self._rewriter.rewrite(context, draft, evidence, findings)
            if rewritten.answer is None or rewritten.answer == draft.answer:
                raise ValueError
        except Exception:
            return self._finalize(
                context,
                draft,
                decision=ReviewDecision.BLOCK,
                findings=_merge_findings(
                    findings, (ReviewFinding(code=ReviewFindingCode.REWRITE_INVALID),)
                ),
                reviewer_execution=ReviewerExecutionOutcome.REWRITE_FAILURE,
                reviewer_pass_count=1,
                rewrite_count=1,
                evidence_identity_preserved=initial_guard.evidence_identity_preserved,
            )

        rewritten_context = context.model_copy(
            update={"answer_draft": AnswerDraft(text=rewritten.answer)}
        )
        rewritten_guard = self._guard.assess(
            rewritten_context, rewritten, selected_evidence_identity=selected_identity
        )
        rewritten_findings = _merge_findings(findings, rewritten_guard.findings)
        if not rewritten_guard.passes:
            return self._finalize(
                context,
                draft,
                decision=ReviewDecision.BLOCK,
                findings=_merge_findings(
                    rewritten_findings, (ReviewFinding(code=ReviewFindingCode.REWRITE_INVALID),)
                ),
                reviewer_execution=ReviewerExecutionOutcome.REWRITE_FAILURE,
                reviewer_pass_count=1,
                rewrite_count=1,
                evidence_identity_preserved=rewritten_guard.evidence_identity_preserved,
            )

        post_rewrite, post_execution = await self._review_once(
            rewritten_context, rewritten, evidence
        )
        if post_rewrite is None:
            return self._finalize(
                context,
                rewritten,
                decision=self._fallback_decision(rewritten_context, rewritten_findings),
                findings=_merge_findings(
                    rewritten_findings,
                    (
                        ReviewFinding(
                            code=(
                                ReviewFindingCode.REVIEWER_OUTPUT_INVALID
                                if post_execution is ReviewerExecutionOutcome.INVALID_OUTPUT
                                else ReviewFindingCode.REVIEWER_UNAVAILABLE
                            )
                        ),
                    ),
                ),
                reviewer_execution=post_execution,
                reviewer_pass_count=1,
                rewrite_count=1,
                evidence_identity_preserved=rewritten_guard.evidence_identity_preserved,
            )
        final_findings = _merge_findings(rewritten_guard.findings, post_rewrite.findings)
        if post_rewrite.decision is ReviewDecision.REVISE:
            return self._finalize(
                context,
                rewritten,
                decision=ReviewDecision.BLOCK,
                findings=_merge_findings(
                    final_findings, (ReviewFinding(code=ReviewFindingCode.REWRITE_EXHAUSTED),)
                ),
                reviewer_execution=post_execution,
                reviewer_pass_count=2,
                rewrite_count=1,
                evidence_identity_preserved=rewritten_guard.evidence_identity_preserved,
            )
        return self._finalize(
            context,
            rewritten,
            decision=post_rewrite.decision,
            findings=final_findings,
            reviewer_execution=post_execution,
            reviewer_pass_count=2,
            rewrite_count=1,
            evidence_identity_preserved=rewritten_guard.evidence_identity_preserved,
        )

    async def _review_once(self, context, draft, evidence):
        if self._provider is None:
            return None, ReviewerExecutionOutcome.PROVIDER_FAILURE
        try:
            generated = await asyncio.wait_for(
                self._provider.generate(
                    GenerationRequest(
                        input_text=build_reviewer_prompt(context, draft, evidence),
                        max_output_tokens=self._settings.max_output_tokens,
                        structured_output=_review_output_format(),
                        reasoning_effort=ReasoningEffort.MINIMAL,
                        verbosity=OutputVerbosity.LOW,
                    )
                ),
                timeout=self._settings.timeout_seconds,
            )
            if generated.finish_reason in {"length", "max_output_tokens"}:
                raise ValueError
            proposal = self._parser.parse(
                generated.text,
                claim_count=len(draft.claims),
                sub_intent_count=len(context.sub_intents),
                evidence_count=len(evidence),
            )
            return proposal, ReviewerExecutionOutcome.REVIEWED
        except ValueError:
            return None, ReviewerExecutionOutcome.INVALID_OUTPUT
        except Exception:
            return None, ReviewerExecutionOutcome.PROVIDER_FAILURE

    def _finalize(
        self,
        context,
        composition: CompositionResult,
        *,
        decision: ReviewDecision,
        findings: tuple[ReviewFinding, ...],
        reviewer_execution: ReviewerExecutionOutcome,
        reviewer_pass_count: int,
        rewrite_count: int,
        evidence_identity_preserved: bool,
    ) -> P11ReviewContextResult:
        final_draft = context.answer_draft
        if rewrite_count and composition.answer is not None:
            final_draft = AnswerDraft(text=composition.answer)
        review = P11ReviewResult(
            decision=decision,
            findings=findings,
            reviewer_execution=reviewer_execution,
            reviewer_pass_count=reviewer_pass_count,
            rewrite_count=rewrite_count,
            guard_outcome=_guard_outcome(decision),
            evidence_identity_preserved=evidence_identity_preserved,
        )
        reviewed_context = advance_case(
            context,
            CaseStage.ANSWER_REVIEWED,
            answer_draft=final_draft,
            review_result=ReviewResult(
                decision=decision,
                finding_codes=tuple(dict.fromkeys(finding.code.value for finding in findings)),
                rewrite_count=rewrite_count,
            ),
        )
        return P11ReviewContextResult(
            context=reviewed_context, result=review, composition=composition
        )

    @staticmethod
    def _fallback_decision(context, findings: tuple[ReviewFinding, ...]) -> ReviewDecision:
        if _has_fatal_guard_failure(findings) or any(
            entry.state is CoverageState.UNSUPPORTED for entry in context.coverage_matrix.entries
        ):
            return ReviewDecision.BLOCK
        return ReviewDecision.PARTIAL


def _merge_findings(*groups: tuple[ReviewFinding, ...]) -> tuple[ReviewFinding, ...]:
    merged: list[ReviewFinding] = []
    seen: set[tuple[object, ...]] = set()
    for finding in (item for group in groups for item in group):
        key = (
            finding.code,
            finding.claim_indices,
            finding.sub_intent_indices,
            finding.evidence_indices,
        )
        if key not in seen:
            seen.add(key)
            merged.append(finding)
    return tuple(merged)


def _has_fatal_guard_failure(findings: tuple[ReviewFinding, ...]) -> bool:
    return any(
        finding.code
        in {
            ReviewFindingCode.EVIDENCE_PACK_DRIFT,
            ReviewFindingCode.COMPOSITION_DRAFT_MISMATCH,
        }
        for finding in findings
    )


def _guard_outcome(decision: ReviewDecision) -> P11GuardOutcome:
    if decision is ReviewDecision.PASS:
        return P11GuardOutcome.P12_CANDIDATE_ONLY
    if decision is ReviewDecision.BLOCK:
        return P11GuardOutcome.BLOCKED_NOT_RELEASABLE
    return P11GuardOutcome.PARTIAL_NOT_RELEASABLE


def _review_output_format() -> StructuredOutputFormat:
    finding_properties: dict[str, Any] = {
        "code": {"type": "string", "enum": [code.value for code in ReviewFindingCode]},
        "claim_indices": {"type": "array", "items": {"type": "integer", "minimum": 0}},
        "sub_intent_indices": {
            "type": "array",
            "items": {"type": "integer", "minimum": 0},
        },
        "evidence_indices": {
            "type": "array",
            "items": {"type": "integer", "minimum": 0},
        },
    }
    return StructuredOutputFormat(
        name="legal_answer_review",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["decision", "findings"],
            "properties": {
                "decision": {"type": "string", "enum": [item.value for item in ReviewDecision]},
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": list(finding_properties),
                        "properties": finding_properties,
                    },
                },
            },
        },
    )


def _composition_output_format() -> StructuredOutputFormat:
    return StructuredOutputFormat(
        name="evidence_bound_rewrite",
        json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["answer", "claims"],
            "properties": {
                "answer": {"type": "string"},
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "claim_index",
                            "kind",
                            "sub_intent_indices",
                            "evidence_indices",
                        ],
                        "properties": {
                            "claim_index": {"type": "integer", "minimum": 0},
                            "kind": {
                                "type": "string",
                                "enum": [item.value for item in ClaimKind],
                            },
                            "sub_intent_indices": {
                                "type": "array",
                                "items": {"type": "integer", "minimum": 0},
                            },
                            "evidence_indices": {
                                "type": "array",
                                "items": {"type": "integer", "minimum": 0},
                            },
                        },
                    },
                },
            },
        },
    )


def _parse_composition_result(output: str) -> CompositionResult:
    try:
        value = json.loads(output, object_pairs_hook=_reject_duplicate_keys)
        if (
            not isinstance(value, dict)
            or set(value) != {"answer", "claims"}
            or not isinstance(value["answer"], str)
            or not value["answer"].strip()
            or not isinstance(value["claims"], list)
        ):
            raise ValueError
        claims = tuple(AnswerClaim.model_validate(item) for item in value["claims"])
        return CompositionResult(answer=value["answer"], claims=claims, enabled=True)
    except Exception:
        raise ValueError("P11 rewrite output is invalid") from None


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError
        value[key] = item
    return value


__all__ = [
    "DraftRewriterPort",
    "EvidenceBoundDraftRewriter",
    "LegalAnswerReviewService",
    "ReviewEvidenceReaderPort",
]
