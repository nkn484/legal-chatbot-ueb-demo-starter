"""Channel-neutral processing status and bounded runtime ETA estimation."""

from __future__ import annotations

from collections import deque
from enum import StrEnum
from math import ceil

from pydantic import BaseModel, ConfigDict, Field


class EtaConfidence(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ProcessingStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    correlation_id: str | None = Field(default=None, max_length=128)
    message: str = Field(min_length=1, max_length=500)
    estimated_wait_min_seconds: int = Field(ge=1, le=300)
    estimated_wait_max_seconds: int = Field(ge=1, le=300)
    confidence: EtaConfidence
    source: str


class RuntimeEtaEstimator:
    """Small in-memory EWMA estimator; no request text or secrets are retained."""

    def __init__(
        self,
        *,
        initial_min_seconds: int = 30,
        initial_max_seconds: int = 60,
        window_size: int = 20,
    ) -> None:
        self._initial_min_seconds = initial_min_seconds
        self._initial_max_seconds = initial_max_seconds
        self._durations_ms: deque[float] = deque(maxlen=window_size)

    def estimate(self, correlation_id: str | None = None) -> ProcessingStatus:
        if not self._durations_ms:
            minimum, maximum, confidence, source = (
                self._initial_min_seconds,
                self._initial_max_seconds,
                EtaConfidence.LOW,
                "CONFIGURED_FALLBACK",
            )
        else:
            average = sum(self._durations_ms) / len(self._durations_ms)
            midpoint = max(1, ceil(average / 1_000))
            minimum = max(1, int(midpoint * 0.8))
            maximum = max(minimum + 5, int(midpoint * 1.3) + 5)
            confidence = (
                EtaConfidence.HIGH if len(self._durations_ms) >= 10 else EtaConfidence.MEDIUM
            )
            source = "ROLLING_RUNTIME_TELEMETRY"
        message = (
            "Đang tra cứu và đối chiếu các căn cứ pháp lý liên quan. "
            f"Dự kiến khoảng {minimum}–{maximum} giây, kết quả sẽ được gửi ngay khi hoàn tất."
        )
        return ProcessingStatus(
            correlation_id=correlation_id,
            message=message,
            estimated_wait_min_seconds=minimum,
            estimated_wait_max_seconds=maximum,
            confidence=confidence,
            source=source,
        )

    def record(self, total_duration_ms: float) -> None:
        if total_duration_ms >= 0:
            self._durations_ms.append(total_duration_ms)


__all__ = ["EtaConfidence", "ProcessingStatus", "RuntimeEtaEstimator"]
