"""P4 authority-role proposal service with deterministic validation and fallback."""

from __future__ import annotations

import asyncio

from legal_chatbot.legal_evidence.discovery.service import BroadDiscoveryResult
from legal_chatbot.legal_evidence.models import AuthorityRole, CaseStage
from legal_chatbot.legal_evidence.transitions import advance_case
from legal_chatbot.providers.models import GenerationRequest
from legal_chatbot.providers.port import LLMProviderPort

from .models import (
    AuthorityMetadata,
    AuthorityReviewOutcome,
    AuthorityReviewResult,
    AuthorityReviewSettings,
    validate_authority_candidate,
)
from .parser import StrictAuthorityProposalParser


def _prompt(candidate_count: int) -> str:
    return "\n".join(
        (
            "Propose one authority role per candidate only.",
            "Do not decide legal effect, applicability, relation, or legal truth.",
            'Return exactly JSON: {"candidates":[{"candidate_index":0,"role":"BACKGROUND"}]}.',
            f"There are exactly {candidate_count} candidates.",
            f"Candidate indices are 0 through {candidate_count - 1}.",
        )
    )


class AuthorityReviewService:
    def __init__(
        self,
        provider: LLMProviderPort | None,
        settings: AuthorityReviewSettings | None = None,
        parser: StrictAuthorityProposalParser | None = None,
    ) -> None:
        self._provider = provider
        self._settings = settings or AuthorityReviewSettings()
        self._parser = parser or StrictAuthorityProposalParser()

    async def review(
        self,
        discovery: BroadDiscoveryResult,
        metadata: tuple[AuthorityMetadata, ...],
    ) -> AuthorityReviewResult:
        if discovery.context.stage is not CaseStage.DISCOVERED:
            raise ValueError("authority review requires discovered context")
        if tuple(item.document for item in metadata) != tuple(
            item.document for item in discovery.workspace.documents
        ):
            raise ValueError("authority metadata must match discovery workspace order")
        roles, outcome, proposal_only = await self._propose(len(metadata))
        candidates = tuple(
            validate_authority_candidate(item, role, proposal_only=proposal_only)
            for item, role in zip(metadata, roles, strict=True)
        )
        return AuthorityReviewResult(candidates=candidates, outcome=outcome)

    async def review_context(
        self,
        discovery: BroadDiscoveryResult,
        metadata: tuple[AuthorityMetadata, ...],
    ) -> AuthorityReviewResult:
        result = await self.review(discovery, metadata)
        updated = advance_case(
            discovery.context,
            CaseStage.AUTHORITY_REVIEWED,
            authority_candidates=result.candidates,
        )
        return AuthorityReviewResult(
            candidates=updated.authority_candidates, outcome=result.outcome
        )

    async def _propose(
        self, candidate_count: int
    ) -> tuple[tuple[AuthorityRole, ...], AuthorityReviewOutcome, bool]:
        fallback = tuple(AuthorityRole.BACKGROUND for _ in range(candidate_count))
        if not self._settings.enabled:
            return fallback, AuthorityReviewOutcome.DISABLED_FALLBACK, False
        if self._provider is None:
            return fallback, AuthorityReviewOutcome.PROVIDER_FAILURE_FALLBACK, False
        try:
            generated = await asyncio.wait_for(
                self._provider.generate(
                    GenerationRequest(
                        input_text=_prompt(candidate_count),
                        max_output_tokens=self._settings.max_output_tokens,
                    )
                ),
                timeout=self._settings.timeout_seconds,
            )
            proposals = self._parser.parse(generated.text, candidate_count=candidate_count)
            roles = tuple(
                next(item.role for item in proposals if item.candidate_index == index)
                for index in range(candidate_count)
            )
            return roles, AuthorityReviewOutcome.LLM_PROPOSALS, True
        except ValueError:
            return fallback, AuthorityReviewOutcome.INVALID_OUTPUT_FALLBACK, False
        except Exception:
            return fallback, AuthorityReviewOutcome.PROVIDER_FAILURE_FALLBACK, False


__all__ = ["AuthorityReviewService"]
