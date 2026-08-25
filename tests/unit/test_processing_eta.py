from datetime import UTC, datetime

import pytest

from legal_chatbot.channels.models import ChannelInboundMessage
from legal_chatbot.channels.service import ChannelService
from legal_chatbot.legal_evidence.processing import EtaConfidence, RuntimeEtaEstimator
from legal_chatbot.legal_evidence.routing import LegalStageModelRoutingSettings


def test_eta_uses_configured_range_until_runtime_telemetry_exists() -> None:
    estimator = RuntimeEtaEstimator(initial_min_seconds=30, initial_max_seconds=60)

    initial = estimator.estimate("correlation")
    estimator.record(10_000)
    measured = estimator.estimate("correlation")

    assert (initial.estimated_wait_min_seconds, initial.estimated_wait_max_seconds) == (30, 60)
    assert initial.confidence is EtaConfidence.LOW
    assert measured.source == "ROLLING_RUNTIME_TELEMETRY"
    assert measured.estimated_wait_min_seconds < measured.estimated_wait_max_seconds


def test_authorized_stage_budgets_are_configurable_per_stage() -> None:
    settings = LegalStageModelRoutingSettings(
        LEGAL_P2_TIMEOUT_SECONDS=18,
        LEGAL_P4_TIMEOUT_SECONDS=25,
    )

    assert settings.p2_timeout_seconds == 18
    assert settings.p4_timeout_seconds == 25


class _Notifier:
    def __init__(self) -> None:
        self.calls = 0

    async def notify(self, message) -> None:
        self.calls += 1


@pytest.mark.asyncio
async def test_processing_status_is_sent_once_per_existing_delivery_identity() -> None:
    notifier = _Notifier()
    service = ChannelService(
        object(), object(), object(), object(), object(), object(), notifier
    )
    message = ChannelInboundMessage(
        identity_hmac="a" * 64,
        delivery_hmac="b" * 64,
        text="private question",
        received_at=datetime.now(UTC),
    )

    await service._notify_processing_once(message)
    await service._notify_processing_once(message)

    assert notifier.calls == 1
