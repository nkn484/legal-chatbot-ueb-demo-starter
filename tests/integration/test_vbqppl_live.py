"""Opt-in live verification of manifest-approved VBQPPL REST fallback reads."""

import json
import os
import time

import pytest

from legal_chatbot.sources.adapters.rest import VBQPPLRestAdapter
from legal_chatbot.sources.config import SourceSettings
from legal_chatbot.sources.registry import load_registry

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_VBQPPL_REST_LIVE") != "1",
    reason="set RUN_VBQPPL_REST_LIVE=1 for the approved VBQPPL REST read",
)
async def test_vbqppl_live_lists_and_fetches_a_manifest_approved_document() -> None:
    settings = SourceSettings()
    source = load_registry(settings.registry_path).get("VBQPPL")
    assert source is not None
    adapter = VBQPPLRestAdapter(settings, source)
    started_at = time.perf_counter()
    try:
        refs = await adapter.list_documents()
        listed_at = time.perf_counter()
        snapshot = await adapter.fetch_document(refs[0])
        fetched_at = time.perf_counter()
    finally:
        await adapter.aclose()

    assert refs
    assert bool(snapshot.content_html)
    print(
        json.dumps(
            {
                "probe": "vbqppl_rest_adapter_live",
                "listed_count": len(refs),
                "fetched": snapshot.source_id == "VBQPPL",
                "content_chars": len(snapshot.content_html),
                "hash_present": bool(snapshot.content_sha256),
                "canonical": bool(snapshot.canonical_url),
                "total_duration_ms": round((fetched_at - started_at) * 1000, 3),
                "list_duration_ms": round((listed_at - started_at) * 1000, 3),
                "fetch_duration_ms": round((fetched_at - listed_at) * 1000, 3),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
