"""Safety tests for the isolated, diagnostic-only TLS exception spike."""

import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from spikes.m08_2 import vbqppl_untrusted_discovery as spike

from legal_chatbot.sources.models import FetchApprovedDocumentRef


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
def reviewed_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a minimal regular-file repo fixture with only the fixed artifact target."""
    root = tmp_path / "repo"
    manifest = root / spike.MANIFEST_RELATIVE_PATH
    artifact = root / spike.ARTIFACT_RELATIVE_PATH
    manifest.parent.mkdir(parents=True)
    artifact.parent.mkdir(parents=True)
    manifest.write_bytes(
        (Path(__file__).resolve().parents[2] / spike.MANIFEST_RELATIVE_PATH).read_bytes()
    )
    monkeypatch.setattr(spike, "REPOSITORY_ROOT", root)
    return artifact


def _wsdl() -> bytes:
    return b"<definitions/>"


def _response(number: str, identifier: str = "200001") -> bytes:
    return (
        f"<GetListVanBanByListSKHResult><VanBanItem><ID>{identifier}</ID>"
        f"<VBPQSokyhieu>{number}</VBPQSokyhieu></VanBanItem>"
        "</GetListVanBanByListSKHResult>"
    ).encode()


def _number(request: httpx.Request) -> str:
    body = request.content.decode("utf-8")
    return body.split("<skh>", 1)[1].split("</skh>", 1)[0]


def _read(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_command_requires_acknowledgement_and_accepts_no_output_or_arbitrary_arguments() -> None:
    with pytest.raises(SystemExit) as missing_ack:
        spike.main([])
    with pytest.raises(SystemExit) as arbitrary:
        spike.main(
            [
                "--acknowledge-untrusted-diagnostic",
                "--output",
                "docs/evidence/anything.json",
            ]
        )
    assert missing_ack.value.code == arbitrary.value.code == 2


@pytest.mark.asyncio
async def test_preflight_or_manifest_failure_makes_zero_client_calls(
    reviewed_artifact: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    constructed = 0

    def factory() -> httpx.AsyncClient:
        nonlocal constructed
        constructed += 1
        return _client(lambda _: httpx.Response(500))

    monkeypatch.setattr(spike, "WSDL_URL", "http://ws.vbpl.vn/vbqppl.asmx?WSDL")
    assert await spike.run_diagnostic(factory) == 2
    assert constructed == 0
    assert _read(reviewed_artifact)["network_calls"] == {"soap_post": 0, "total": 0, "wsdl_get": 0}

    monkeypatch.setattr(spike, "WSDL_URL", "https://ws.vbpl.vn/vbqppl.asmx?WSDL")
    monkeypatch.setattr(spike, "load_manifest", lambda _: (_ for _ in ()).throw(ValueError("bad")))
    assert await spike.run_diagnostic(factory) == 2
    assert constructed == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "attempt",
    [
        Path("contracts/vbqppl-read-manifest.json"),
        Path("contracts/source-registry.json"),
        Path(".env"),
        Path("src/legal_chatbot/main.py"),
        Path("../outside.json"),
        Path("C:/outside.json"),
    ],
)
async def test_nonreviewed_or_external_output_targets_are_rejected_pre_client_and_write(
    reviewed_artifact: Path, monkeypatch: pytest.MonkeyPatch, attempt: Path
) -> None:
    constructed = 0
    before = reviewed_artifact.read_bytes() if reviewed_artifact.exists() else None

    def factory() -> httpx.AsyncClient:
        nonlocal constructed
        constructed += 1
        return _client(lambda _: httpx.Response(500))

    monkeypatch.setattr(spike, "ARTIFACT_RELATIVE_PATH", attempt)
    assert await spike.run_diagnostic(factory) == 2
    assert constructed == 0
    assert (reviewed_artifact.read_bytes() if reviewed_artifact.exists() else None) == before


@pytest.mark.asyncio
async def test_symlinked_artifact_parent_is_rejected_before_client_or_external_write(
    reviewed_artifact: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    evidence = reviewed_artifact.parent
    external = tmp_path / "external"
    external.mkdir()
    evidence.rmdir()
    try:
        evidence.symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable on this Windows test host")
    constructed = 0

    def factory() -> httpx.AsyncClient:
        nonlocal constructed
        constructed += 1
        return _client(lambda _: httpx.Response(500))

    assert await spike.run_diagnostic(factory) == 2
    assert constructed == 0
    assert not (external / spike.ARTIFACT_RELATIVE_PATH.name).exists()


def test_artifact_write_atomically_replaces_a_regular_target_and_leaves_no_temp_files(
    reviewed_artifact: Path,
) -> None:
    reviewed_artifact.write_text('{"old":true}\n', encoding="utf-8")
    before_inode = reviewed_artifact.stat().st_ino

    spike._write_artifact(reviewed_artifact, {"safe": True})

    assert _read(reviewed_artifact) == {"safe": True}
    after_inode = reviewed_artifact.stat().st_ino
    if before_inode and after_inode:
        assert after_inode != before_inode
    assert not list(reviewed_artifact.parent.glob(f".{reviewed_artifact.name}.*.tmp"))


def test_hard_linked_artifact_target_is_rejected_without_altering_trusted_manifest(
    reviewed_artifact: Path,
) -> None:
    manifest = reviewed_artifact.parents[2] / spike.MANIFEST_RELATIVE_PATH
    before = manifest.read_bytes()
    try:
        os.link(manifest, reviewed_artifact)
    except OSError:
        pytest.skip("hard links are unavailable on this filesystem")

    with pytest.raises(spike._DiagnosticFailure):
        spike._write_artifact(reviewed_artifact, {"safe": True})

    assert manifest.read_bytes() == before
    assert reviewed_artifact.read_bytes() == before
    assert reviewed_artifact.stat().st_nlink > 1


def test_failed_atomic_replace_cleans_temporary_file(
    reviewed_artifact: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_replace(_: Path, __: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(spike.os, "replace", fail_replace)
    with pytest.raises(spike._DiagnosticFailure):
        spike._write_artifact(reviewed_artifact, {"safe": True})

    assert not list(reviewed_artifact.parent.glob(f".{reviewed_artifact.name}.*.tmp"))


@pytest.mark.asyncio
async def test_fixed_batch_preserves_exact_32_order_and_network_cap(
    reviewed_artifact: Path,
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200, content=_wsdl() if request.method == "GET" else _response(_number(request))
        )

    exit_code = await spike.run_diagnostic(lambda: _client(handler))
    artifact = _read(reviewed_artifact)
    expected = [
        request.document_number
        for request in spike.load_manifest(
            reviewed_artifact.parents[2] / spike.MANIFEST_RELATIVE_PATH
        ).discovery_requests()
    ]

    assert exit_code == 0
    assert [request.method for request in calls] == ["GET"] + ["POST"] * 32
    assert artifact["network_calls"] == {"soap_post": 32, "total": 33, "wsdl_get": 1}
    assert artifact["success_count"] == 32
    assert artifact["failure_count"] == 0
    outcomes = artifact["outcomes"]
    assert isinstance(outcomes, list)
    assert [item["document_number"] for item in outcomes] == expected
    assert all(
        item["trust_level"] == "UNTRUSTED"
        and item["tls_verified"] is False
        and item["fetch_allowed"] is False
        and item["ingestion_allowed"] is False
        and item["citation_allowed"] is False
        for item in outcomes
    )


@pytest.mark.asyncio
async def test_mixed_post_failures_continue_and_emit_safe_complete_artifact(
    reviewed_artifact: Path,
) -> None:
    post_count = 0
    sentinel = "PRIVATE-XML-TITLE"

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_count
        if request.method == "GET":
            return httpx.Response(200, content=_wsdl())
        post_count += 1
        if post_count == 2:
            return httpx.Response(200, content=f"<broken>{sentinel}".encode())
        return httpx.Response(200, content=_response(_number(request)))

    assert await spike.run_diagnostic(lambda: _client(handler)) == 1
    rendered = reviewed_artifact.read_text(encoding="utf-8")
    artifact = json.loads(rendered)

    assert (artifact["success_count"], artifact["failure_count"]) == (31, 1)
    assert len(artifact["outcomes"]) == 32
    assert artifact["outcomes"][1]["error"] == "invalid_response"
    assert post_count == 32
    assert sentinel not in rendered
    assert "ws.vbpl.vn" not in rendered
    assert "GetVanBanById" not in rendered


@pytest.mark.parametrize(
    "payload",
    [
        b"<!DOCTYPE x><x/>",
        b"<broken>",
        b"<soap:Fault xmlns:soap='x'/>",
        b"<GetListVanBanByListSKHResult><VanBanItem><ID>1</ID><VBPQSokyhieu>x</VBPQSokyhieu></VanBanItem><VanBanItem><ID>2</ID><VBPQSokyhieu>x</VBPQSokyhieu></VanBanItem></GetListVanBanByListSKHResult>",
        b"<GetListVanBanByListSKHResult><VanBanItem><ID>0</ID><VBPQSokyhieu>x</VBPQSokyhieu></VanBanItem></GetListVanBanByListSKHResult>",
        b"<GetListVanBanByListSKHResult><VanBanItem><ID>1</ID><VBPQSokyhieu>other</VBPQSokyhieu></VanBanItem></GetListVanBanByListSKHResult>",
    ],
)
def test_xml_rejections_never_produce_a_candidate(payload: bytes) -> None:
    with pytest.raises(spike._DiagnosticFailure):
        spike._select_candidate(payload, "x")


def test_oversized_xml_is_rejected_without_a_candidate() -> None:
    with pytest.raises(spike._DiagnosticFailure):
        spike._select_candidate(b"x" * (spike.MAX_RESPONSE_BYTES + 1), "x")


@pytest.mark.asyncio
async def test_manifest_bytes_remain_unchanged_and_candidate_is_not_fetch_capability(
    reviewed_artifact: Path,
) -> None:
    manifest = reviewed_artifact.parents[2] / spike.MANIFEST_RELATIVE_PATH
    before = manifest.read_bytes()
    before_hash = hashlib.sha256(before).hexdigest()

    assert (
        await spike.run_diagnostic(
            lambda: _client(
                lambda request: httpx.Response(
                    200, content=_wsdl() if request.method == "GET" else _response(_number(request))
                )
            )
        )
        == 0
    )

    candidate = spike.UntrustedCandidate(document_number="125/2025/QH15", discovered_id="200001")
    with pytest.raises(ValidationError):
        FetchApprovedDocumentRef.model_validate(asdict(candidate))
    assert manifest.read_bytes() == before
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == before_hash


def test_production_does_not_import_or_register_the_spike() -> None:
    production_files = Path("src").rglob("*.py")
    assert all(
        "spikes.m08_2" not in path.read_text(encoding="utf-8")
        and "vbqppl_untrusted_discovery" not in path.read_text(encoding="utf-8")
        for path in production_files
    )
