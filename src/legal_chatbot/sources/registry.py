"""Validated source-level registry and exact VBQPPL document manifest loading."""

import json
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from legal_chatbot.sources.config import SourceSettings
from legal_chatbot.sources.errors import SourceError
from legal_chatbot.sources.models import (
    DiscoveryRequest,
    FetchApprovedDocumentRef,
    SourceErrorCode,
)
from legal_chatbot.sources.port import LegalSourceDiscoveryPort, LegalSourcePort

_SOURCE_PRIORITIES = {"VBQPPL": 1, "VNU": 2, "UEB": 3}
_VBQPPL_SOAP_OPERATIONS = ("GetListVanBanByListSKH", "GetVanBanById")


class SourceSystemConfig(BaseModel):
    """Source lifecycle and transport authority only; never document authorization."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Literal["VBQPPL", "VNU", "UEB"]
    priority: Literal[1, 2, 3]
    lifecycle: Literal["ACTIVE", "PLANNED"]
    demo_implementation: Literal["DEMO_NOW", "LATER"]
    transport: str = Field(min_length=1, max_length=64)
    base_url: str | None = None
    access_mode: str = Field(min_length=1, max_length=128)
    fallback_transport: str | None = None
    fallback_base_url: str | None = None
    fallback_access_mode: str | None = None
    fallback_lifecycle: str | None = None
    canonical_page_origin: str | None = None
    soap_operation_allowlist: tuple[str, ...] = ()
    fallback_notes: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_source_contract(self) -> "SourceSystemConfig":
        if self.priority != _SOURCE_PRIORITIES[self.id]:
            raise ValueError("priority must match the fixed rollout order")
        if self.id == "VBQPPL":
            if self.lifecycle != "ACTIVE" or self.demo_implementation != "DEMO_NOW":
                raise ValueError("VBQPPL must be active for the demo")
            if self.soap_operation_allowlist != _VBQPPL_SOAP_OPERATIONS:
                raise ValueError("VBQPPL SOAP operations must use the exact allowlist")
        elif self.lifecycle != "PLANNED" or self.demo_implementation != "LATER":
            raise ValueError(f"{self.id} must remain planned")
        elif self.base_url is not None or self.fallback_base_url is not None:
            raise ValueError(f"{self.id} may not declare source URLs")
        return self


class SourceRegistryData(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1]
    systems: tuple[SourceSystemConfig, ...]

    @model_validator(mode="after")
    def validate_systems(self) -> "SourceRegistryData":
        ids = tuple(source.id for source in self.systems)
        if len(ids) != len(set(ids)):
            raise ValueError("source system IDs must not be duplicated")
        if set(ids) != set(_SOURCE_PRIORITIES):
            raise ValueError("registry must contain exactly VBQPPL, VNU, and UEB")
        return self

    def get(self, source_id: str) -> SourceSystemConfig | None:
        return next((source for source in self.systems if source.id == source_id), None)


class DiscoveryAllowance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    transport: Literal["SOAP"]
    status: Literal["DISCOVERY_APPROVED", "NOT_APPROVED"]


class FetchPermission(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    transport: Literal["SOAP", "REST_FRONTEND_BACKING_API"]
    status: Literal["PENDING_EXACT_ID", "NOT_APPROVED", "FETCH_APPROVED"]
    document_id: str | None = Field(default=None, min_length=1, max_length=256)
    detail_path: str | None = Field(default=None, pattern=r"^/[^?#]*$")
    canonical_url: str | None = Field(default=None, min_length=1, max_length=2_048)

    @model_validator(mode="after")
    def validate_identity(self) -> "FetchPermission":
        approved = self.status == "FETCH_APPROVED"
        if approved != all((self.document_id, self.detail_path, self.canonical_url)):
            raise ValueError(
                "fetch approval must have complete exact identity and all other states null"
            )
        if self.transport == "SOAP" and self.status == "NOT_APPROVED":
            raise ValueError("SOAP permissions use pending or fetch-approved status")
        if self.transport == "REST_FRONTEND_BACKING_API" and self.status == "PENDING_EXACT_ID":
            raise ValueError("REST permissions use not-approved or fetch-approved status")
        if self.canonical_url is not None:
            parsed = urlsplit(self.canonical_url)
            if (
                parsed.scheme != "https"
                or parsed.hostname is None
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("canonical URL must be an exact HTTPS page URL")
        return self


class ManifestDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    document_number: str = Field(min_length=1, max_length=256)
    purpose: tuple[str, ...] = Field(min_length=1, max_length=16)
    discovery: DiscoveryAllowance
    fetch_permissions: tuple[FetchPermission, ...] = Field(max_length=2)

    @model_validator(mode="after")
    def validate_permissions(self) -> "ManifestDocument":
        transports = tuple(permission.transport for permission in self.fetch_permissions)
        if len(transports) != len(set(transports)):
            raise ValueError("each document transport-specific fetch permission must be unique")
        return self

    def fetch_ref(self, transport: str) -> FetchApprovedDocumentRef | None:
        permission = next(
            (
                value
                for value in self.fetch_permissions
                if value.transport == transport and value.status == "FETCH_APPROVED"
            ),
            None,
        )
        if permission is None:
            return None
        operation = "GetVanBanById" if transport == "SOAP" else f"GET {permission.detail_path}"
        return FetchApprovedDocumentRef(
            source_id="VBQPPL",
            external_id=permission.document_id or "",
            document_number=self.document_number,
            canonical_url=permission.canonical_url,
            transport=transport,
            detail_path=permission.detail_path or "",
            operation=operation,
        )


class VBQPPLReadManifest(BaseModel):
    """The sole trusted document-level discovery and fetch authorization contract."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1]
    source_id: Literal["VBQPPL"]
    documents: tuple[ManifestDocument, ...] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_document_authorization(self) -> "VBQPPLReadManifest":
        numbers = tuple(document.document_number for document in self.documents)
        if len(numbers) != len(set(numbers)):
            raise ValueError("manifest document numbers must be unique")
        return self

    def discovery_requests(self) -> tuple[DiscoveryRequest, ...]:
        return tuple(
            DiscoveryRequest(
                source_id=self.source_id,
                document_number=document.document_number,
                transport="SOAP",
            )
            for document in self.documents
            if document.discovery.status == "DISCOVERY_APPROVED"
        )

    def fetch_refs(self, transport: str | None = None) -> tuple[FetchApprovedDocumentRef, ...]:
        return tuple(
            ref
            for document in self.documents
            for candidate_transport in ("SOAP", "REST_FRONTEND_BACKING_API")
            if (ref := document.fetch_ref(candidate_transport)) is not None
            and (transport is None or ref.transport == transport)
        )


def load_registry(path: Path) -> SourceRegistryData:
    with path.open(encoding="utf-8") as source_file:
        return SourceRegistryData.model_validate(json.load(source_file))


def load_manifest(path: Path) -> VBQPPLReadManifest:
    with path.open(encoding="utf-8") as manifest_file:
        return VBQPPLReadManifest.model_validate(json.load(manifest_file))


type SourceFactory = Callable[
    [SourceSettings, SourceSystemConfig, VBQPPLReadManifest, httpx.AsyncClient | None],
    LegalSourcePort,
]


def _normalize_source_id(source_id: str) -> str:
    return source_id.strip().upper()


class SourceAdapterRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, SourceFactory] = {}

    def register(self, source_id: str, factory: SourceFactory) -> None:
        normalized_id = _normalize_source_id(source_id)
        if normalized_id not in _SOURCE_PRIORITIES or normalized_id in self._factories:
            raise SourceError(
                SourceErrorCode.SOURCE_NOT_CONFIGURED,
                source_id=normalized_id or "unknown",
                operation="register",
                status_code=400,
            )
        self._factories[normalized_id] = factory

    def create(
        self,
        source_id: str,
        settings: SourceSettings,
        source: SourceSystemConfig,
        manifest: VBQPPLReadManifest,
        client: httpx.AsyncClient | None = None,
    ) -> LegalSourcePort:
        normalized_id = _normalize_source_id(source_id)
        factory = self._factories.get(normalized_id)
        if factory is None:
            raise SourceError(
                SourceErrorCode.SOURCE_NOT_CONFIGURED,
                source_id=normalized_id or "unknown",
                operation="create",
                status_code=503,
            )
        return factory(settings, source, manifest, client)


def _create_vbqppl(
    settings: SourceSettings,
    source: SourceSystemConfig,
    manifest: VBQPPLReadManifest,
    client: httpx.AsyncClient | None,
) -> LegalSourcePort:
    module_name = (
        "legal_chatbot.sources.adapters.rest"
        if settings.vbqppl_mode == "rest_fallback"
        else "legal_chatbot.sources.adapters.soap"
    )
    adapter_module = import_module(module_name)
    adapter_name = (
        "VBQPPLRestAdapter" if settings.vbqppl_mode == "rest_fallback" else "VBQPPLSoapAdapter"
    )
    return getattr(adapter_module, adapter_name)(settings, source, client=client, manifest=manifest)


def _create_not_implemented(
    settings: SourceSettings,
    source: SourceSystemConfig,
    manifest: VBQPPLReadManifest,
    client: httpx.AsyncClient | None,
) -> LegalSourcePort:
    del settings, manifest, client
    from legal_chatbot.sources.adapters.not_implemented import NotImplementedSourceAdapter

    return NotImplementedSourceAdapter(source)


def create_default_registry() -> SourceAdapterRegistry:
    registry = SourceAdapterRegistry()
    registry.register("VBQPPL", _create_vbqppl)
    registry.register("VNU", _create_not_implemented)
    registry.register("UEB", _create_not_implemented)
    return registry


def create_source(
    source_id: str,
    settings: SourceSettings,
    registry_data: SourceRegistryData | None = None,
    client: httpx.AsyncClient | None = None,
    manifest_data: VBQPPLReadManifest | None = None,
) -> LegalSourcePort:
    """Compose one registry-declared source.

    ``registry_data``, ``manifest_data``, and ``client`` are test/DI seams only;
    document authorization always remains the validated manifest, never caller input.
    """
    normalized_id = _normalize_source_id(source_id)
    resolved_data = registry_data or load_registry(settings.registry_path)
    source = resolved_data.get(normalized_id)
    if source is None:
        raise SourceError(
            SourceErrorCode.SOURCE_NOT_CONFIGURED,
            source_id=normalized_id or "unknown",
            operation="create",
            status_code=503,
        )
    manifest = manifest_data or load_manifest(settings.vbqppl_read_manifest_path)
    return create_default_registry().create(normalized_id, settings, source, manifest, client)


def create_discovery_source(
    settings: SourceSettings,
    registry_data: SourceRegistryData | None = None,
    manifest_data: VBQPPLReadManifest | None = None,
    client: httpx.AsyncClient | None = None,
) -> LegalSourceDiscoveryPort:
    """Create the SOAP-only manifest-driven discovery adapter.

    Injected registry, manifest, and client values are test/DI seams, not a source
    authorization boundary.
    """
    source = (registry_data or load_registry(settings.registry_path)).get("VBQPPL")
    if source is None:
        raise SourceError(
            SourceErrorCode.SOURCE_NOT_CONFIGURED,
            source_id="VBQPPL",
            operation="create_discovery",
            status_code=503,
        )
    manifest = manifest_data or load_manifest(settings.vbqppl_read_manifest_path)
    adapter_module = import_module("legal_chatbot.sources.adapters.soap")
    return adapter_module.VBQPPLSoapAdapter(settings, source, client=client, manifest=manifest)
