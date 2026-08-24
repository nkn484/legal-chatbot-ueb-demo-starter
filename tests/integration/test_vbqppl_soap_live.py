"""Opt-in, sanitized live health evidence for the residual VBQPPL SOAP lane."""

import json
import os
from pathlib import Path

import pytest

from legal_chatbot.sources.adapters.soap import VBQPPLSoapAdapter
from legal_chatbot.sources.config import SourceSettings
from legal_chatbot.sources.models import SourceHealthStatus
from legal_chatbot.sources.registry import load_registry

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_VBQPPL_SOAP_LIVE") != "1",
    reason="set RUN_VBQPPL_SOAP_LIVE=1 for the bounded VBQPPL SOAP health probe",
)
async def test_vbqppl_soap_live_health_only() -> None:
    source = load_registry(Path("contracts/source-registry.json")).get("VBQPPL")
    assert source is not None
    adapter = VBQPPLSoapAdapter(SourceSettings(), source)
    try:
        health = await adapter.health_check()
    finally:
        await adapter.aclose()

    print(
        json.dumps(
            {
                "probe": "vbqppl_soap_adapter_live",
                "outcome": (
                    "PASS" if health.status is SourceHealthStatus.HEALTHY else "BLOCKED_EXTERNAL"
                ),
                "status": health.status.value,
                "error_code": health.error_code.value if health.error_code else None,
                "tls_verified": SourceSettings().soap_tls_verify,
                "wsdl_requests": 1,
                "soap_posts": 0,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
