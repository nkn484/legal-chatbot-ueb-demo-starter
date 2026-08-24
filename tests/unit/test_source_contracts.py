"""Unit coverage for the M03 source core contracts and registry boundary."""

import copy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from legal_chatbot.sources import (
    LegalDocumentSnapshot,
    ProvenanceType,
    SourceError,
    SourceErrorCode,
    SourceHealthStatus,
    SourceProvenance,
    SourceSettings,
    create_source,
    load_manifest,
    load_registry,
)
from legal_chatbot.sources.models import TransportTrustMode
from legal_chatbot.sources.registry import SourceAdapterRegistry

REGISTRY_PATH = Path("contracts/source-registry.json")
MANIFEST_PATH = Path("contracts/vbqppl-read-manifest.json")
CANONICAL_URL = "https://vbpl.vn/van-ban/chi-tiet/luat-to-chuc-chinh-phu-so-63-2025-qh15--175258"
KNOWN_DOCUMENT = {
    "document_id": "175258",
    "document_number": "63/2025/QH15",
    "detail_path": "/qtdc/public/doc/175258",
    "canonical_url": CANONICAL_URL,
}


def test_registry_is_source_level_and_manifest_is_exact_document_authority() -> None:
    registry = load_registry(REGISTRY_PATH)
    assert [(source.id, source.priority) for source in registry.systems] == [
        ("VBQPPL", 1),
        ("VNU", 2),
        ("UEB", 3),
    ]
    assert registry.get("VBQPPL").notes == "Priority is rollout order, not legal authority ranking."
    vbqppl = registry.get("VBQPPL")
    assert vbqppl is not None
    assert vbqppl.soap_operation_allowlist == ("GetListVanBanByListSKH", "GetVanBanById")
    assert "read_allowlist" not in vbqppl.model_dump_json()
    manifest = load_manifest(MANIFEST_PATH)
    assert len(manifest.documents) == 33
    assert len(manifest.discovery_requests()) == 32
    assert manifest.fetch_refs("SOAP")[0].model_dump(
        exclude={"transport", "operation", "source_id"}
    ) == {
        "external_id": KNOWN_DOCUMENT["document_id"],
        "document_number": KNOWN_DOCUMENT["document_number"],
        "detail_path": KNOWN_DOCUMENT["detail_path"],
        "canonical_url": KNOWN_DOCUMENT["canonical_url"],
    }
    assert len(manifest.fetch_refs("REST_FRONTEND_BACKING_API")) == 1
    assert registry.get("VNU").base_url is None
    assert registry.get("UEB").base_url is None


def test_registry_rejects_duplicate_ids() -> None:
    payload = load_registry(REGISTRY_PATH).model_dump(mode="json")
    payload["systems"].append(payload["systems"][0])
    with pytest.raises(ValidationError, match="duplicated"):
        type(load_registry(REGISTRY_PATH)).model_validate(payload)


def test_manifest_schema_allows_future_exact_entries_without_python_literal_changes() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    payload = copy.deepcopy(manifest.model_dump(mode="json"))
    payload["documents"].append(
        {
            "document_number": "future/2026/QH16",
            "purpose": ["FUTURE_APPROVAL"],
            "discovery": {"transport": "SOAP", "status": "DISCOVERY_APPROVED"},
            "fetch_permissions": [],
        }
    )

    evolved = type(manifest).model_validate(payload)

    assert len(evolved.documents) == 34
    assert evolved.discovery_requests()[-1].document_number == "future/2026/QH16"
    assert len(evolved.fetch_refs()) == 2


def test_manifest_rejects_generic_duplicate_and_incomplete_fetch_permissions() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    duplicate = copy.deepcopy(manifest.model_dump(mode="json"))
    duplicate["documents"].append(copy.deepcopy(duplicate["documents"][0]))
    with pytest.raises(ValidationError, match="numbers must be unique"):
        type(manifest).model_validate(duplicate)

    incomplete = copy.deepcopy(manifest.model_dump(mode="json"))
    incomplete["documents"][0]["fetch_permissions"] = [
        {
            "transport": "SOAP",
            "status": "FETCH_APPROVED",
            "document_id": "200001",
            "detail_path": None,
            "canonical_url": None,
        }
    ]
    with pytest.raises(ValidationError, match="complete exact identity"):
        type(manifest).model_validate(incomplete)


def test_source_models_are_immutable_hashable_and_validate_timezone_and_hash() -> None:
    retrieved_at = datetime.now(UTC)
    provenance = SourceProvenance(
        provenance_type=ProvenanceType.SOURCE_FETCH,
        source_id="VBQPPL",
        transport="REST_FRONTEND_BACKING_API",
        operation="read_document",
        retrieved_at=retrieved_at,
        canonical_url=CANONICAL_URL,
        tls_verified=True,
    )
    snapshot = LegalDocumentSnapshot(
        source_id="VBQPPL",
        external_id="175258",
        content_html="<article>content</article>",
        content_sha256="a" * 64,
        provenance=provenance,
    )
    assert hash(snapshot)
    with pytest.raises(ValidationError, match="frozen"):
        snapshot.source_id = "VNU"  # type: ignore[misc]
    with pytest.raises(ValidationError, match="timezone-aware"):
        SourceProvenance(
            provenance_type=ProvenanceType.SOURCE_FETCH,
            source_id="VBQPPL",
            transport="REST",
            operation="read",
            retrieved_at=datetime.now(),
            tls_verified=True,
        )
    with pytest.raises(ValidationError):
        LegalDocumentSnapshot(
            source_id="VBQPPL",
            external_id="175258",
            content_html="content",
            content_sha256="A" * 64,
            provenance=provenance,
        )
    with pytest.raises(ValidationError, match="snapshot source_id must match provenance source_id"):
        LegalDocumentSnapshot(
            source_id="VNU",
            external_id="175258",
            content_html="content",
            content_sha256="a" * 64,
            provenance=provenance,
        )
    with pytest.raises(
        ValidationError, match="snapshot canonical_url must match provenance canonical_url"
    ):
        LegalDocumentSnapshot(
            source_id="VBQPPL",
            external_id="175258",
            canonical_url="https://example.invalid/different",
            content_html="content",
            content_sha256="a" * 64,
            provenance=provenance,
        )


def test_source_provenance_backfills_trust_and_requires_complete_tofu_metadata() -> None:
    strict = SourceProvenance(
        provenance_type=ProvenanceType.SOURCE_FETCH,
        source_id="VBQPPL",
        transport="SOAP",
        operation="fetch_document",
        retrieved_at=datetime(2026, 8, 21, tzinfo=UTC),
        tls_verified=True,
    )
    legacy = SourceProvenance(
        provenance_type=ProvenanceType.SOURCE_FETCH,
        source_id="VBQPPL",
        transport="SOAP",
        operation="fetch_document",
        retrieved_at=datetime(2026, 8, 21, tzinfo=UTC),
        tls_verified=False,
    )
    assert (
        strict.transport_trust_mode,
        strict.tls_chain_verified,
        strict.tls_hostname_verified,
    ) == (TransportTrustMode.STRICT_TLS, True, True)
    assert (
        legacy.transport_trust_mode,
        legacy.tls_chain_verified,
        legacy.tls_hostname_verified,
    ) == (TransportTrustMode.LEGACY_UNVERIFIED, False, False)

    digest = sha256(b"trust-metadata").hexdigest()
    certificate_not_before = datetime(2026, 6, 10, tzinfo=UTC)
    tofu_fields = {
        "transport_trust_mode": TransportTrustMode.USER_APPROVED_TOFU_PINNED_EXCEPTION,
        "tls_chain_verified": True,
        "tls_hostname_verified": False,
        "trust_exception_id": "vbqppl-tofu-2026",
        "trust_exception_digest": digest,
        "policy_id": "vbqppl-policy-1",
        "policy_version": 1,
        "compiled_policy_digest": digest,
        "registry_snapshot_digest": digest,
        "pin_set_id": "vbqppl-pins-2026",
        "pin_set_version": 1,
        "pin_set_digest": digest,
        "matched_pin_id": "ws-vbpl-spki-1",
        "peer_certificate_not_before": certificate_not_before,
        "peer_certificate_not_after": certificate_not_before + timedelta(days=30),
        "acquisition_correlation_id": "acquisition-20260821-1",
    }
    tofu = SourceProvenance(
        provenance_type=ProvenanceType.SOURCE_FETCH,
        source_id="VBQPPL",
        transport="SOAP",
        operation="fetch_document",
        retrieved_at=datetime(2026, 8, 21, tzinfo=UTC),
        tls_verified=False,
        **tofu_fields,
    )
    assert tofu.transport_trust_mode is TransportTrustMode.USER_APPROVED_TOFU_PINNED_EXCEPTION
    assert tofu.tls_verified is False
    with pytest.raises(ValidationError, match="complete trust"):
        SourceProvenance(
            provenance_type=ProvenanceType.SOURCE_FETCH,
            source_id="VBQPPL",
            transport="SOAP",
            operation="fetch_document",
            retrieved_at=datetime(2026, 8, 21, tzinfo=UTC),
            tls_verified=False,
            transport_trust_mode=TransportTrustMode.USER_APPROVED_TOFU_PINNED_EXCEPTION,
            tls_chain_verified=True,
            tls_hostname_verified=False,
        )
    with pytest.raises(ValidationError, match="tls_verified must equal"):
        SourceProvenance(
            provenance_type=ProvenanceType.SOURCE_FETCH,
            source_id="VBQPPL",
            transport="SOAP",
            operation="fetch_document",
            retrieved_at=datetime(2026, 8, 21, tzinfo=UTC),
            tls_verified=True,
            **tofu_fields,
        )


def test_source_error_is_safe_and_normalized() -> None:
    error = SourceError(
        SourceErrorCode.ACCESS_DENIED,
        source_id="VBQPPL",
        operation="fetch_document",
        retryable=False,
        status_code=403,
    )
    assert str(error) == "access_denied"
    assert (error.source_id, error.operation, error.status_code) == (
        "VBQPPL",
        "fetch_document",
        403,
    )
    assert SourceError(SourceErrorCode.TIMEOUT, source_id="bad\nvalue").source_id == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("source_id", ["VNU", "UEB"])
async def test_future_sources_are_not_implemented_without_network(source_id: str) -> None:
    adapter = create_source(source_id, SourceSettings())
    with pytest.raises(SourceError) as exc_info:
        await adapter.list_documents()
    assert exc_info.value.code is SourceErrorCode.SOURCE_NOT_IMPLEMENTED


@pytest.mark.asyncio
async def test_future_source_aclose_does_not_mask_an_operational_error() -> None:
    adapter = create_source("VNU", SourceSettings())
    with pytest.raises(SourceError) as exc_info:
        try:
            await adapter.list_documents()
        finally:
            await adapter.aclose()
    assert exc_info.value.code is SourceErrorCode.SOURCE_NOT_IMPLEMENTED


def test_unknown_and_duplicate_source_factories_fail_safely() -> None:
    settings = SourceSettings()
    with pytest.raises(SourceError) as unknown:
        create_source("UNKNOWN", settings)
    assert unknown.value.code is SourceErrorCode.SOURCE_NOT_CONFIGURED
    registry = SourceAdapterRegistry()
    registry.register("VNU", lambda _settings, _source, _client: object())
    with pytest.raises(SourceError) as duplicate:
        registry.register("VNU", lambda _settings, _source, _client: object())
    assert duplicate.value.code is SourceErrorCode.SOURCE_NOT_CONFIGURED


def test_source_settings_defaults_aliases_and_bounds() -> None:
    settings = SourceSettings(VBQPPL_TLS_VERIFY="false", ignored_setting="ignored")
    assert settings.registry_path == REGISTRY_PATH
    assert settings.vbqppl_read_manifest_path == MANIFEST_PATH
    assert settings.vbqppl_mode == "rest_fallback"
    assert settings.rest_max_response_bytes == settings.soap_max_response_bytes == 2_097_152
    assert settings.soap_tls_verify is False
    assert SourceHealthStatus.HEALTHY.value == "healthy"
    with pytest.raises(ValidationError):
        SourceSettings(VBQPPL_REST_MAX_ATTEMPTS=4)
