"""Pure, code-owned source-adapter capability declarations for policy simulation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

_MAX_CAPABILITIES = 32
_MAX_CONTENT_TYPES = 8
_MAX_PARSER_PROFILES = 8
_SAFE_HOST = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9-]+)+$")
_SAFE_PATH = re.compile(r"^/[A-Za-z0-9._/-]{2,255}$")
_SAFE_TOKEN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_SAFE_ACTION = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")
_SAFE_TEMPLATE_ID = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
_SAFE_CONTENT_TYPE = re.compile(
    r"^[a-z0-9][a-z0-9!#$&^_.+-]{0,63}/[a-z0-9][a-z0-9!#$&^_.+-]{0,63}$"
)


def _require_token(value: str, name: str) -> None:
    if not isinstance(value, str) or not _SAFE_TOKEN.fullmatch(value):
        raise ValueError(f"{name} must be an exact bounded token")


def _require_exact_values(
    values: tuple[str, ...],
    name: str,
    pattern: re.Pattern[str],
    maximum: int,
) -> None:
    if (
        not isinstance(values, tuple)
        or not 1 <= len(values) <= maximum
        or len(values) != len(set(values))
    ):
        raise ValueError(f"{name} must be a bounded unique tuple")
    if any(not isinstance(value, str) or not pattern.fullmatch(value) for value in values):
        raise ValueError(f"{name} contains an unsafe value")


@dataclass(frozen=True)
class AdapterCapability:
    """A declarative lower capability, not an adapter, network client, or fetch authority."""

    source_id: str
    transport: str
    host: str
    endpoint: str
    action: str
    access_mode_requirement: str
    discovery_mode: str
    template_id: str
    allowed_content_types: tuple[str, ...]
    parser_profiles: tuple[str, ...]
    requires_exact_document_numbers: bool
    simulation_only: bool = True

    def __post_init__(self) -> None:
        _require_token(self.source_id, "source_id")
        _require_token(self.transport, "transport")
        _require_token(self.access_mode_requirement, "access_mode_requirement")
        _require_token(self.discovery_mode, "discovery_mode")
        if (
            not isinstance(self.host, str)
            or self.host != self.host.lower()
            or not _SAFE_HOST.fullmatch(self.host)
        ):
            raise ValueError("host must be a normalized exact hostname")
        if (
            not isinstance(self.endpoint, str)
            or not _SAFE_PATH.fullmatch(self.endpoint)
            or "//" in self.endpoint
        ):
            raise ValueError("endpoint must be an exact bounded path")
        if not isinstance(self.action, str) or not _SAFE_ACTION.fullmatch(self.action):
            raise ValueError("action must be an exact bounded action")
        if not isinstance(self.template_id, str) or not _SAFE_TEMPLATE_ID.fullmatch(
            self.template_id
        ):
            raise ValueError("template_id must be an exact bounded token")
        _require_exact_values(
            self.allowed_content_types,
            "allowed_content_types",
            _SAFE_CONTENT_TYPE,
            _MAX_CONTENT_TYPES,
        )
        _require_exact_values(
            self.parser_profiles,
            "parser_profiles",
            _SAFE_TOKEN,
            _MAX_PARSER_PROFILES,
        )
        if not isinstance(self.requires_exact_document_numbers, bool):
            raise ValueError("requires_exact_document_numbers must be a boolean")
        if self.simulation_only is not True:
            raise ValueError("adapter capabilities must be simulation-only")


@dataclass(frozen=True)
class AdapterCapabilityTable:
    """Immutable, bounded table of code-owned source shapes for policy simulation."""

    version: int
    capabilities: tuple[AdapterCapability, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.version, int)
            or isinstance(self.version, bool)
            or self.version != 1
            or not isinstance(self.capabilities, tuple)
        ):
            raise ValueError("adapter capability table is invalid")
        if not 1 <= len(self.capabilities) <= _MAX_CAPABILITIES:
            raise ValueError("adapter capability table is invalid")
        if not all(isinstance(capability, AdapterCapability) for capability in self.capabilities):
            raise ValueError("adapter capability table contains an invalid capability")
        shapes = tuple(
            (
                capability.source_id,
                capability.transport,
                capability.host,
                capability.endpoint,
                capability.action,
                capability.access_mode_requirement,
                capability.discovery_mode,
                capability.template_id,
            )
            for capability in self.capabilities
        )
        if len(shapes) != len(set(shapes)):
            raise ValueError("adapter capabilities must not be duplicated")

    def find(
        self,
        *,
        source_id: str,
        transport: str,
        host: str,
        endpoint: str,
        action: str,
        access_mode_requirement: str,
        discovery_mode: str,
        template_id: str,
    ) -> AdapterCapability | None:
        return next(
            (
                capability
                for capability in self.capabilities
                if capability.source_id == source_id
                and capability.transport == transport
                and capability.host == host
                and capability.endpoint == endpoint
                and capability.action == action
                and capability.access_mode_requirement == access_mode_requirement
                and capability.discovery_mode == discovery_mode
                and capability.template_id == template_id
            ),
            None,
        )

    def canonical_data(self) -> dict[str, object]:
        return {
            "version": self.version,
            "capabilities": [
                {
                    "source_id": value.source_id,
                    "transport": value.transport,
                    "host": value.host,
                    "endpoint": value.endpoint,
                    "action": value.action,
                    "access_mode_requirement": value.access_mode_requirement,
                    "discovery_mode": value.discovery_mode,
                    "template_id": value.template_id,
                    "allowed_content_types": list(value.allowed_content_types),
                    "parser_profiles": list(value.parser_profiles),
                    "requires_exact_document_numbers": value.requires_exact_document_numbers,
                    "simulation_only": value.simulation_only,
                }
                for value in self.capabilities
            ],
        }


CURRENT_ADAPTER_CAPABILITIES: Final = AdapterCapabilityTable(
    version=1,
    capabilities=(
        AdapterCapability(
            source_id="VBQPPL",
            transport="SOAP",
            host="ws.vbpl.vn",
            endpoint="/vbqppl.asmx",
            action="GetListVanBanByListSKH",
            access_mode_requirement="READ_ONLY_POLICY_ALLOWLIST",
            discovery_mode="EXACT_DOCUMENT_NUMBER",
            template_id="vbqppl_soap_exact_number_v1",
            allowed_content_types=("text/xml",),
            parser_profiles=("SOAP_XML_V1",),
            requires_exact_document_numbers=True,
        ),
    ),
)
