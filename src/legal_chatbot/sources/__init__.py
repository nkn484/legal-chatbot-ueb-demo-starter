"""Lazy public exports for source-neutral legal contracts and factories.

Keeping this package initializer dependency-free lets Phase 0 policy modules remain
pure when imported as ``legal_chatbot.sources.<module>``.  Runtime source machinery
is imported only when a caller explicitly requests its public export.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "DiscoveryCandidate": ("legal_chatbot.sources.models", "DiscoveryCandidate"),
    "DiscoveryRequest": ("legal_chatbot.sources.models", "DiscoveryRequest"),
    "FetchApprovedDocumentRef": ("legal_chatbot.sources.models", "FetchApprovedDocumentRef"),
    "LegalDocumentSnapshot": ("legal_chatbot.sources.models", "LegalDocumentSnapshot"),
    "LegalSourceDiscoveryPort": ("legal_chatbot.sources.port", "LegalSourceDiscoveryPort"),
    "LegalSourcePort": ("legal_chatbot.sources.port", "LegalSourcePort"),
    "ProvenanceType": ("legal_chatbot.sources.models", "ProvenanceType"),
    "SourceAdapterRegistry": ("legal_chatbot.sources.registry", "SourceAdapterRegistry"),
    "SourceDocumentRef": ("legal_chatbot.sources.models", "SourceDocumentRef"),
    "SourceError": ("legal_chatbot.sources.errors", "SourceError"),
    "SourceErrorCode": ("legal_chatbot.sources.models", "SourceErrorCode"),
    "SourceHealth": ("legal_chatbot.sources.models", "SourceHealth"),
    "SourceHealthStatus": ("legal_chatbot.sources.models", "SourceHealthStatus"),
    "SourceProvenance": ("legal_chatbot.sources.models", "SourceProvenance"),
    "SourceRegistryData": ("legal_chatbot.sources.registry", "SourceRegistryData"),
    "SourceSettings": ("legal_chatbot.sources.config", "SourceSettings"),
    "SourceSystemConfig": ("legal_chatbot.sources.registry", "SourceSystemConfig"),
    "VBQPPLReadManifest": ("legal_chatbot.sources.registry", "VBQPPLReadManifest"),
    "create_default_registry": ("legal_chatbot.sources.registry", "create_default_registry"),
    "create_discovery_source": ("legal_chatbot.sources.registry", "create_discovery_source"),
    "create_source": ("legal_chatbot.sources.registry", "create_source"),
    "load_manifest": ("legal_chatbot.sources.registry", "load_manifest"),
    "load_registry": ("legal_chatbot.sources.registry", "load_registry"),
}

__all__ = [*_EXPORTS, "discovery_cli"]


def __getattr__(name: str) -> Any:
    """Resolve public exports only on explicit access, avoiding eager runtime imports."""

    if name == "discovery_cli":
        module = import_module("legal_chatbot.sources.discovery_cli")
        globals()[name] = module
        return module
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as error:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from error
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted([*globals(), *__all__])
