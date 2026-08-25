"""Application entrypoint for channel-neutral P1-P10 legal chat requests."""

from __future__ import annotations

from enum import StrEnum
from time import perf_counter
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from legal_chatbot.legal_evidence.models import CoverageState
from legal_chatbot.legal_evidence.processing import ProcessingStatus, RuntimeEtaEstimator


class LegalChatStatus(StrEnum):
    ANSWER = "ANSWER"
    EVIDENCE_LIMITED = "EVIDENCE_LIMITED"
    UNAVAILABLE = "UNAVAILABLE"


class LegalChatResponse(BaseModel):
    """Channel-neutral legal answer with private implementation state excluded."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    answer_text: str = Field(min_length=1, max_length=4_000)
    status: LegalChatStatus
    limitations: tuple[str, ...] = ()
    correlation_id: str | None = Field(default=None, max_length=128)
    total_duration_ms: float = Field(ge=0)
    eta_min_seconds: int | None = Field(default=None, ge=1, le=300)
    eta_max_seconds: int | None = Field(default=None, ge=1, le=300)


class LegalEvidenceInvestigatorPort(Protocol):
    async def investigate(self, question: str): ...


class LegalChatApplication:
    """Own the legal-pipeline request path so channels never call individual phases."""

    def __init__(
        self,
        investigator: LegalEvidenceInvestigatorPort,
        eta_estimator: RuntimeEtaEstimator | None = None,
    ) -> None:
        self._investigator = investigator
        self._eta_estimator = eta_estimator or RuntimeEtaEstimator()

    def processing_status(self, correlation_id: str | None = None) -> ProcessingStatus:
        return self._eta_estimator.estimate(correlation_id)

    async def ask(
        self, question: str, *, correlation_id: str | None = None
    ) -> LegalChatResponse:
        started = perf_counter()
        eta = self.processing_status(correlation_id)
        try:
            context = await self._investigator.investigate(question)
            draft = context.answer_draft
            if draft is None:
                raise RuntimeError("LEGAL_ANSWER_DRAFT_UNAVAILABLE")
            limited = tuple(
                item
                for item in context.coverage_matrix.entries
                if item.state is not CoverageState.SUPPORTED
            )
            limitations = tuple(
                f"COVERAGE_{item.state.value}" for item in limited
            ) or context.limitations
            duration = max(0, (perf_counter() - started) * 1_000)
            self._eta_estimator.record(duration)
            return LegalChatResponse(
                answer_text=draft.text,
                status=(
                    LegalChatStatus.EVIDENCE_LIMITED if limitations else LegalChatStatus.ANSWER
                ),
                limitations=limitations,
                correlation_id=correlation_id,
                total_duration_ms=duration,
                eta_min_seconds=eta.estimated_wait_min_seconds,
                eta_max_seconds=eta.estimated_wait_max_seconds,
            )
        except Exception:
            duration = max(0, (perf_counter() - started) * 1_000)
            self._eta_estimator.record(duration)
            return LegalChatResponse(
                answer_text="Hệ thống hiện chưa thể truy xuất đầy đủ căn cứ để trả lời an toàn.",
                status=LegalChatStatus.UNAVAILABLE,
                limitations=("LEGAL_PIPELINE_UNAVAILABLE",),
                correlation_id=correlation_id,
                total_duration_ms=duration,
                eta_min_seconds=eta.estimated_wait_min_seconds,
                eta_max_seconds=eta.estimated_wait_max_seconds,
            )


__all__ = ["LegalChatApplication", "LegalChatResponse", "LegalChatStatus"]
