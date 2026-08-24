"""Opt-in live verification for the SHINE SHOP provider adapter."""

import json
import os

import pytest

from legal_chatbot.providers.adapters.shineshop import ShineShopAdapter
from legal_chatbot.providers.config import ProviderSettings
from legal_chatbot.providers.models import (
    GenerationRequest,
    ProviderHealthStatus,
)

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_SHINE_LIVE") != "1", reason="set RUN_SHINE_LIVE=1 for live SHINE"
)
async def test_shineshop_live_health_and_single_bounded_generation() -> None:
    settings = ProviderSettings()
    adapter = ShineShopAdapter(settings)
    try:
        health = await adapter.health_check()
        assert health.status is ProviderHealthStatus.HEALTHY
        assert health.model == settings.model
        result = await adapter.generate(
            GenerationRequest(input_text="Reply exactly READY.", max_output_tokens=20)
        )
    finally:
        await adapter.aclose()

    assert bool(result.text.strip())
    print(
        json.dumps(
            {
                "probe": "shineshop_adapter_live",
                "outcome": "PASS",
                "provider": result.provider,
                "model": result.model,
                "health_request_id": health.request_id,
                "health_duration_ms": round(health.duration_ms, 3),
                "generation_request_id": result.request_id,
                "generation_duration_ms": round(result.duration_ms, 3),
                "output_text_chars": len(result.text),
                "generation_attempts": 1,
                "stream": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
