"""Unit coverage for bounded, content-safe manifest-driven discovery output."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from legal_chatbot.sources import discovery_cli
from legal_chatbot.sources.discovery import discover_manifest
from legal_chatbot.sources.errors import SourceError
from legal_chatbot.sources.models import DiscoveryCandidate, DiscoveryRequest, SourceErrorCode
from legal_chatbot.sources.registry import load_manifest


class FakeDiscoverySource:
    def __init__(self, failures: dict[str, SourceErrorCode] | None = None) -> None:
        self.failures = failures or {}
        self.requests: list[DiscoveryRequest] = []
        self.closed = False

    async def discover_document(self, request: DiscoveryRequest) -> DiscoveryCandidate:
        self.requests.append(request)
        if (code := self.failures.get(request.document_number)) is not None:
            raise SourceError(code, source_id="VBQPPL", operation="discover")
        return DiscoveryCandidate(
            source_id=request.source_id,
            document_number=request.document_number,
            external_id="sanitized-id",
            transport=request.transport,
        )

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_discovery_service_continues_mixed_results_in_exact_manifest_order() -> None:
    manifest = load_manifest(Path("contracts/vbqppl-read-manifest.json"))
    approved = manifest.discovery_requests()
    source = FakeDiscoverySource(
        {
            approved[1].document_number: SourceErrorCode.DOCUMENT_NOT_FOUND,
            approved[-1].document_number: SourceErrorCode.TIMEOUT,
        }
    )

    outcomes = await discover_manifest(source, manifest)

    assert len(outcomes) == 32
    assert tuple(outcome.document_number for outcome in outcomes) == tuple(
        request.document_number for request in approved
    )
    assert tuple(request.document_number for request in source.requests) == tuple(
        request.document_number for request in approved
    )
    assert outcomes[0].success is True
    assert outcomes[1].error_code is SourceErrorCode.DOCUMENT_NOT_FOUND
    assert outcomes[-1].error_code is SourceErrorCode.TIMEOUT
    assert all("content" not in outcome.payload() for outcome in outcomes)


@pytest.mark.asyncio
async def test_cli_writes_complete_safe_artifact_and_returns_nonzero_on_item_failures(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = load_manifest(Path("contracts/vbqppl-read-manifest.json"))
    source = FakeDiscoverySource(
        {manifest.discovery_requests()[0].document_number: SourceErrorCode.UNAVAILABLE}
    )
    settings = SimpleNamespace(
        registry_path=Path("contracts/source-registry.json"),
        vbqppl_read_manifest_path=Path("contracts/vbqppl-read-manifest.json"),
    )
    monkeypatch.setattr(discovery_cli, "SourceSettings", lambda: settings)
    monkeypatch.setattr(discovery_cli, "configure_logging", lambda _: None)
    monkeypatch.setattr(discovery_cli, "load_registry", lambda _: object())
    monkeypatch.setattr(discovery_cli, "load_manifest", lambda _: manifest)
    monkeypatch.setattr(discovery_cli, "create_discovery_source", lambda *_: source)

    exit_code = await discovery_cli.run()
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert source.closed is True
    assert payload["event"] == "discovery_results"
    assert (payload["success_count"], payload["failure_count"]) == (31, 1)
    assert len(payload["outcomes"]) == 32
    assert [item["document_number"] for item in payload["outcomes"]] == [
        request.document_number for request in manifest.discovery_requests()
    ]
    assert payload["outcomes"][0] == {
        "document_number": manifest.discovery_requests()[0].document_number,
        "error": "unavailable",
        "outcome": "failure",
    }
    assert "sanitized-id" in json.dumps(payload)
    assert "exception" not in json.dumps(payload)
