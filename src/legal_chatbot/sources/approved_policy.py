"""Pure Phase 0 approved-source-policy contract loading and subset compilation.

This module deliberately has no adapter, HTTP, port, grant, fetch, ingestion, retrieval, database,
provider, channel, or runtime dependency. Compilation is simulation-only and cannot authorize I/O.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, date, datetime
from enum import Enum, StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from legal_chatbot.sources.adapter_capabilities import AdapterCapabilityTable

if TYPE_CHECKING:
    from legal_chatbot.sources.registry import SourceRegistryData


_MAX_POLICIES = 32
_MAX_LIST_ITEMS = 32
_MAX_EXACT_DOCUMENT_NUMBERS = 8
_MAX_CONTENT_BYTES = 2_097_152
_MAX_DATE_RANGE_DAYS = 1_827
_MIN_CONTRACT_DATE = date(2000, 1, 1)
_MAX_CONTRACT_DATE = date(2100, 12, 31)
_SAFE_TEXT = re.compile(r"^[^\x00-\x1f\x7f]{1,256}$")
_SAFE_POLICY_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,95}$")
_SAFE_NUMBER = re.compile(r"^[0-9A-Za-zÀ-ỹĐđ._/-]{1,128}$")
_SAFE_PATH = re.compile(r"^/[A-Za-z0-9._/-]{2,255}$")
_SAFE_HOST = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9-]+)+$")
_SAFE_TOKEN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_SAFE_TEMPLATE_ID = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
_SAFE_ACTION = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")
_SAFE_CONTENT_TYPE = re.compile(
    r"^[a-z0-9][a-z0-9!#$&^_.+-]{0,63}/[a-z0-9][a-z0-9!#$&^_.+-]{0,63}$"
)
_UNSAFE_LITERAL = re.compile(r"[\\*+?\[\]{}()|^$]")
_LIMIT_MAXIMA = {
    "max_calls_per_request": 8,
    "max_calls_per_policy_window": 64,
    "max_results_per_discovery": 32,
    "max_documents_per_request": 16,
    "max_relation_depth": 4,
    "max_elapsed_seconds": 30,
    "request_timeout_seconds": 15,
    "rate_limit_per_window": 64,
    "circuit_breaker_failure_threshold": 8,
    "circuit_breaker_open_seconds": 300,
}
_LIMIT_NAMES = (
    "max_calls_per_request",
    "max_calls_per_policy_window",
    "max_results_per_discovery",
    "max_documents_per_request",
    "max_relation_depth",
    "max_elapsed_seconds",
    "request_timeout_seconds",
    "rate_limit_per_window",
    "circuit_breaker_failure_threshold",
    "circuit_breaker_open_seconds",
)


class PolicyContractError(ValueError):
    """A checked-in policy contract is invalid or too broad for simulation."""


class PolicyStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class CompilationOutcome(StrEnum):
    COMPILED_SIMULATION = "COMPILED_SIMULATION"
    POLICY_DRAFT = "POLICY_DRAFT"
    POLICY_SUSPENDED = "POLICY_SUSPENDED"
    POLICY_EXPIRED = "POLICY_EXPIRED"
    POLICY_REVOKED = "POLICY_REVOKED"
    ACTIVATION_BLOCKED_REGISTRY_ACCESS_MODE = "ACTIVATION_BLOCKED_REGISTRY_ACCESS_MODE"
    REJECTED_SOURCE_NOT_FOUND = "REJECTED_SOURCE_NOT_FOUND"
    REJECTED_SOURCE_NOT_ACTIVE = "REJECTED_SOURCE_NOT_ACTIVE"
    REJECTED_REGISTRY_SUBSET = "REJECTED_REGISTRY_SUBSET"
    REJECTED_CAPABILITY = "REJECTED_CAPABILITY"


def canonical_json_digest(value: object) -> str:
    """Hash canonical JSON so key order cannot affect policy simulation identity."""

    encoded = json.dumps(
        _normalize_canonical_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalize_canonical_json(value: object) -> object:
    """Convert only explicit, deterministic Phase 0 values to JSON primitives."""

    if isinstance(value, Enum):
        return _normalize_canonical_json(value.value)
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("canonical JSON does not permit naive datetimes")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _normalize_canonical_json(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical JSON mappings must have string keys")
            normalized[key] = _normalize_canonical_json(item)
        return normalized
    if isinstance(value, (tuple, list)):
        return [_normalize_canonical_json(item) for item in value]
    raise TypeError(f"canonical JSON does not support {type(value).__name__}")


def _require_mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PolicyContractError(f"{name} must be an object")
    return value


def _require_exact_keys(data: Mapping[str, Any], name: str, keys: set[str]) -> None:
    if set(data) != keys:
        raise PolicyContractError(f"{name} has unknown or missing fields")


def _require_text(value: object, name: str, *, pattern: re.Pattern[str] = _SAFE_TEXT) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise PolicyContractError(f"{name} is invalid")
    if "*" in value or "://" in value or value.startswith(("http:", "https:")):
        raise PolicyContractError(f"{name} must not contain a URL")
    return value


def _require_list(
    value: object, name: str, *, minimum: int = 0, maximum: int = _MAX_LIST_ITEMS
) -> tuple[str, ...]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise PolicyContractError(f"{name} must be a bounded list")
    values = tuple(_require_text(item, name) for item in value)
    if len(values) != len(set(values)):
        raise PolicyContractError(f"{name} must not contain duplicates")
    return values


def _require_literal_values(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    if any(_UNSAFE_LITERAL.search(value) for value in values):
        raise PolicyContractError(f"{name} must contain exact literals, not matching rules")
    return values


def _parse_timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise PolicyContractError(f"{name} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise PolicyContractError(f"{name} must be an ISO timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PolicyContractError(f"{name} must be timezone-aware")
    normalized = parsed.astimezone(UTC)
    if not _MIN_CONTRACT_DATE <= normalized.date() <= _MAX_CONTRACT_DATE:
        raise PolicyContractError(f"{name} is outside the supported contract range")
    return normalized


def _parse_date(value: object, name: str) -> date:
    if not isinstance(value, str):
        raise PolicyContractError(f"{name} must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise PolicyContractError(f"{name} must be an ISO date") from error
    if not _MIN_CONTRACT_DATE <= parsed <= _MAX_CONTRACT_DATE:
        raise PolicyContractError(f"{name} is outside the supported contract range")
    return parsed


@dataclass(frozen=True)
class AllowDenyConstraint:
    allow: tuple[str, ...]
    deny: tuple[str, ...]

    @classmethod
    def from_data(cls, value: object, name: str, *, minimum_allow: int = 1) -> AllowDenyConstraint:
        data = _require_mapping(value, name)
        _require_exact_keys(data, name, {"allow", "deny"})
        allow = _require_list(data.get("allow"), f"{name}.allow", minimum=minimum_allow)
        deny = _require_list(data.get("deny"), f"{name}.deny")
        if set(allow) & set(deny):
            raise PolicyContractError(f"{name} allow/deny conflict")
        return cls(allow=allow, deny=deny)

    def permits(self, value: str) -> bool:
        """Deny wins for any later candidate validation consumer."""

        return value in self.allow and value not in self.deny


@dataclass(frozen=True)
class ContentConstraints:
    content_types: AllowDenyConstraint
    max_decoded_bytes: int
    parser_profiles: tuple[str, ...]

    @classmethod
    def from_data(cls, value: object) -> ContentConstraints:
        data = _require_mapping(value, "constraints.content")
        _require_exact_keys(
            data,
            "constraints.content",
            {
                "allow_content_types",
                "deny_content_types",
                "max_decoded_bytes",
                "parser_profiles",
            },
        )
        content_types = AllowDenyConstraint.from_data(
            {"allow": data.get("allow_content_types"), "deny": data.get("deny_content_types")},
            "constraints.content.types",
        )
        for content_type in (*content_types.allow, *content_types.deny):
            if not _SAFE_CONTENT_TYPE.fullmatch(content_type):
                raise PolicyContractError("constraints.content types must be exact media types")
        max_decoded_bytes = data.get("max_decoded_bytes")
        if (
            not isinstance(max_decoded_bytes, int)
            or isinstance(max_decoded_bytes, bool)
            or not 1 <= max_decoded_bytes <= _MAX_CONTENT_BYTES
        ):
            raise PolicyContractError("constraints.content.max_decoded_bytes is invalid")
        parser_profiles = _require_list(
            data.get("parser_profiles"),
            "constraints.content.parser_profiles",
            minimum=1,
            maximum=4,
        )
        if any(not _SAFE_TOKEN.fullmatch(profile) for profile in parser_profiles):
            raise PolicyContractError("constraints.content.parser_profiles must be exact tokens")
        return cls(
            content_types=content_types,
            max_decoded_bytes=max_decoded_bytes,
            parser_profiles=parser_profiles,
        )


@dataclass(frozen=True)
class PolicyConstraints:
    document_types: AllowDenyConstraint
    issuers: AllowDenyConstraint
    jurisdictions: AllowDenyConstraint
    titles: AllowDenyConstraint
    paths: AllowDenyConstraint
    date_from: date
    date_to: date
    content: ContentConstraints

    @classmethod
    def from_data(cls, value: object) -> PolicyConstraints:
        data = _require_mapping(value, "constraints")
        _require_exact_keys(
            data,
            "constraints",
            {
                "document_types",
                "issuers",
                "jurisdictions",
                "titles",
                "paths",
                "date_range",
                "content",
            },
        )
        paths = AllowDenyConstraint.from_data(data.get("paths"), "constraints.paths")
        for path in (*paths.allow, *paths.deny):
            if (
                not _SAFE_PATH.fullmatch(path)
                or path == "/"
                or "//" in path
                or _UNSAFE_LITERAL.search(path)
            ):
                raise PolicyContractError("constraints.paths must be exact bounded paths")
        date_range = _require_mapping(data.get("date_range"), "constraints.date_range")
        _require_exact_keys(date_range, "constraints.date_range", {"from", "to"})
        date_from = _parse_date(date_range.get("from"), "constraints.date_range.from")
        date_to = _parse_date(date_range.get("to"), "constraints.date_range.to")
        if date_from > date_to:
            raise PolicyContractError("constraints.date_range is inverted")
        if (date_to - date_from).days > _MAX_DATE_RANGE_DAYS:
            raise PolicyContractError("constraints.date_range is too broad")
        document_types = AllowDenyConstraint.from_data(
            data.get("document_types"), "constraints.document_types"
        )
        issuers = AllowDenyConstraint.from_data(data.get("issuers"), "constraints.issuers")
        jurisdictions = AllowDenyConstraint.from_data(
            data.get("jurisdictions"), "constraints.jurisdictions"
        )
        titles = AllowDenyConstraint.from_data(data.get("titles"), "constraints.titles")
        for name, constraint in (
            ("constraints.document_types", document_types),
            ("constraints.issuers", issuers),
            ("constraints.jurisdictions", jurisdictions),
        ):
            if any(
                not _SAFE_TOKEN.fullmatch(item) for item in (*constraint.allow, *constraint.deny)
            ):
                raise PolicyContractError(f"{name} must contain bounded exact tokens")
        _require_literal_values(titles.allow, "constraints.titles.allow")
        _require_literal_values(titles.deny, "constraints.titles.deny")
        return cls(
            document_types=document_types,
            issuers=issuers,
            jurisdictions=jurisdictions,
            titles=titles,
            paths=paths,
            date_from=date_from,
            date_to=date_to,
            content=ContentConstraints.from_data(data.get("content")),
        )


@dataclass(frozen=True)
class Authority:
    transport: str
    host: str
    endpoint: str
    action: str


@dataclass(frozen=True)
class Discovery:
    mode: str
    template_id: str
    exact_document_numbers: tuple[str, ...]


@dataclass(frozen=True)
class ApprovedSourcePolicy:
    policy_id: str
    version: int
    owner: str
    status: PolicyStatus
    source_id: str
    access_mode_requirement: str
    effective_from: datetime
    effective_to: datetime
    revoked: bool
    authority: Authority
    discovery: Discovery
    constraints: PolicyConstraints
    limits: tuple[tuple[str, int], ...]

    @classmethod
    def from_data(cls, value: object) -> ApprovedSourcePolicy:
        data = _require_mapping(value, "policy")
        _require_exact_keys(
            data,
            "policy",
            {
                "policy_id",
                "version",
                "owner",
                "status",
                "source_id",
                "access_mode_requirement",
                "effective_from",
                "effective_to",
                "revocation",
                "authority",
                "tls",
                "discovery",
                "constraints",
                "limits",
            },
        )
        policy_id = _require_text(data.get("policy_id"), "policy_id", pattern=_SAFE_POLICY_ID)
        version = data.get("version")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise PolicyContractError("version must be positive")
        owner = _require_text(data.get("owner"), "owner")
        try:
            status = PolicyStatus(data.get("status"))
        except (TypeError, ValueError) as error:
            raise PolicyContractError("status is invalid") from error
        source_id = _require_text(data.get("source_id"), "source_id")
        if not _SAFE_TOKEN.fullmatch(source_id):
            raise PolicyContractError("source_id must be an exact bounded token")
        access_mode = _require_text(data.get("access_mode_requirement"), "access_mode_requirement")
        if not _SAFE_TOKEN.fullmatch(access_mode):
            raise PolicyContractError("access_mode_requirement must be an exact bounded token")
        effective_from = _parse_timestamp(data.get("effective_from"), "effective_from")
        effective_to = _parse_timestamp(data.get("effective_to"), "effective_to")
        if effective_from >= effective_to:
            raise PolicyContractError("effective period is invalid")
        if (effective_to.date() - effective_from.date()).days > _MAX_DATE_RANGE_DAYS:
            raise PolicyContractError("effective period is too broad")
        revocation = _require_mapping(data.get("revocation"), "revocation")
        _require_exact_keys(revocation, "revocation", {"status", "reason_code"})
        revoked = revocation.get("status") == "REVOKED"
        if revocation.get("status") not in {"NOT_REVOKED", "REVOKED"}:
            raise PolicyContractError("revocation status is invalid")
        if revoked and not _require_text(revocation.get("reason_code"), "revocation.reason_code"):
            raise PolicyContractError("revoked policy requires reason")
        if not revoked and revocation.get("reason_code") is not None:
            raise PolicyContractError("non-revoked policy must not have reason")
        if status is PolicyStatus.REVOKED and not revoked:
            raise PolicyContractError("REVOKED status requires revoked revocation")
        authority_data = _require_mapping(data.get("authority"), "authority")
        _require_exact_keys(
            authority_data, "authority", {"transport", "host", "endpoint", "action"}
        )
        authority = Authority(
            transport=_require_text(authority_data.get("transport"), "authority.transport"),
            host=_normalize_host(authority_data.get("host")),
            endpoint=_normalize_endpoint(authority_data.get("endpoint")),
            action=_require_text(authority_data.get("action"), "authority.action"),
        )
        if not _SAFE_TOKEN.fullmatch(authority.transport):
            raise PolicyContractError("authority.transport must be an exact bounded token")
        if not _SAFE_ACTION.fullmatch(authority.action):
            raise PolicyContractError("authority.action must be an exact bounded action")
        tls = _require_mapping(data.get("tls"), "tls")
        if tls != {"https_only": True, "verify": True, "allow_redirects": False}:
            raise PolicyContractError("TLS must require HTTPS verify=true and redirects=false")
        discovery_data = _require_mapping(data.get("discovery"), "discovery")
        _require_exact_keys(
            discovery_data,
            "discovery",
            {"mode", "template_id", "exact_document_numbers"},
        )
        mode = _require_text(discovery_data.get("mode"), "discovery.mode")
        if not _SAFE_TOKEN.fullmatch(mode):
            raise PolicyContractError("discovery.mode must be an exact bounded token")
        exact_numbers = _require_list(
            discovery_data.get("exact_document_numbers"),
            "discovery.exact_document_numbers",
            minimum=0,
            maximum=_MAX_EXACT_DOCUMENT_NUMBERS,
        )
        if any(
            not _SAFE_NUMBER.fullmatch(number) or _UNSAFE_LITERAL.search(number)
            for number in exact_numbers
        ):
            raise PolicyContractError("discovery exact document number is invalid")
        template_id = _require_text(discovery_data.get("template_id"), "discovery.template_id")
        if not _SAFE_TEMPLATE_ID.fullmatch(template_id):
            raise PolicyContractError("discovery.template_id must be an exact bounded token")
        limits_data = _require_mapping(data.get("limits"), "limits")
        if set(limits_data) != set(_LIMIT_NAMES):
            raise PolicyContractError("limits must contain exactly the required bounded values")
        limits: list[tuple[str, int]] = []
        for name in _LIMIT_NAMES:
            limit = limits_data[name]
            if (
                not isinstance(limit, int)
                or isinstance(limit, bool)
                or not 1 <= limit <= _LIMIT_MAXIMA[name]
            ):
                raise PolicyContractError(f"limits.{name} is invalid")
            limits.append((name, limit))
        limit_values = dict(limits)
        if limit_values["max_calls_per_request"] > limit_values["max_calls_per_policy_window"]:
            raise PolicyContractError("max_calls_per_request exceeds policy window")
        if limit_values["max_documents_per_request"] > limit_values["max_results_per_discovery"]:
            raise PolicyContractError("max_documents_per_request exceeds discovery results")
        if limit_values["max_results_per_discovery"] > limit_values["max_calls_per_policy_window"]:
            raise PolicyContractError("max_results_per_discovery exceeds policy window calls")
        if limit_values["max_calls_per_policy_window"] > limit_values["rate_limit_per_window"]:
            raise PolicyContractError("max_calls_per_policy_window exceeds rate limit")
        if limit_values["request_timeout_seconds"] > limit_values["max_elapsed_seconds"]:
            raise PolicyContractError("request_timeout_seconds exceeds elapsed timeout")
        return cls(
            policy_id=policy_id,
            version=version,
            owner=owner,
            status=status,
            source_id=source_id,
            access_mode_requirement=access_mode,
            effective_from=effective_from,
            effective_to=effective_to,
            revoked=revoked,
            authority=authority,
            discovery=Discovery(
                mode=mode,
                template_id=template_id,
                exact_document_numbers=exact_numbers,
            ),
            constraints=PolicyConstraints.from_data(data.get("constraints")),
            limits=tuple(limits),
        )

    def canonical_data(self) -> dict[str, object]:
        data = _normalize_canonical_json(self)
        assert isinstance(data, dict)
        return data


@dataclass(frozen=True)
class ApprovedSourcePolicies:
    version: int
    policies: tuple[ApprovedSourcePolicy, ...]

    @classmethod
    def from_data(cls, value: object) -> ApprovedSourcePolicies:
        data = _require_mapping(value, "contract")
        _require_exact_keys(data, "contract", {"version", "policies"})
        if data.get("version") != 1:
            raise PolicyContractError("contract version is unsupported")
        raw_policies = data.get("policies")
        if not isinstance(raw_policies, list) or not 1 <= len(raw_policies) <= _MAX_POLICIES:
            raise PolicyContractError("policies must be a bounded non-empty list")
        policies = tuple(ApprovedSourcePolicy.from_data(policy) for policy in raw_policies)
        revisions = tuple((policy.policy_id, policy.version) for policy in policies)
        if len(revisions) != len(set(revisions)):
            raise PolicyContractError("policy revisions must not be duplicated")
        return cls(version=1, policies=policies)


def _normalize_host(value: object) -> str:
    host = _require_text(value, "authority.host")
    if host != host.lower() or not _SAFE_HOST.fullmatch(host):
        raise PolicyContractError("authority.host must be a normalized exact hostname")
    return host


def _normalize_endpoint(value: object) -> str:
    endpoint = _require_text(value, "authority.endpoint")
    if (
        not _SAFE_PATH.fullmatch(endpoint)
        or "//" in endpoint
        or "?" in endpoint
        or "#" in endpoint
        or _UNSAFE_LITERAL.search(endpoint)
    ):
        raise PolicyContractError("authority.endpoint must be an exact bounded path")
    return endpoint


def load_approved_source_policies(path: Path) -> ApprovedSourcePolicies:
    """Load only the checked-in simulation contract; this performs no source I/O."""

    with path.open(encoding="utf-8") as policy_file:
        return ApprovedSourcePolicies.from_data(json.load(policy_file))


@dataclass(frozen=True)
class CompiledApprovedSourcePolicy:
    """Immutable subset proof only; deliberately not a fetch/grant/reference capability."""

    policy_id: str
    policy_version: int
    source_id: str
    discovery_template_id: str
    policy_digest: str
    registry_digest: str
    capability_digest: str
    outcome: CompilationOutcome
    authorization_eligible: bool

    def audit_record(self, duration_ms: int) -> dict[str, str | int | bool]:
        """Return only content-free observability fields permitted in Phase 0."""

        if not isinstance(duration_ms, int) or isinstance(duration_ms, bool) or duration_ms < 0:
            raise ValueError("duration_ms must be a non-negative integer")
        return {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "source_id": self.source_id,
            "template_id": self.discovery_template_id,
            "outcome": self.outcome.value,
            "duration_ms": duration_ms,
            "authorization_eligible": self.authorization_eligible,
        }


class ApprovedSourcePolicyCompiler:
    """Prove policy subset constraints without runtime wiring or external I/O."""

    def __init__(self, capabilities: AdapterCapabilityTable) -> None:
        self._capabilities = capabilities

    def compile(
        self,
        policy: ApprovedSourcePolicy,
        registry: SourceRegistryData,
        *,
        now: datetime,
    ) -> CompiledApprovedSourcePolicy:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        registry_digest = canonical_json_digest(registry.model_dump(mode="json"))
        capability_digest = canonical_json_digest(self._capabilities.canonical_data())
        policy_digest = canonical_json_digest(policy.canonical_data())
        source = registry.get(policy.source_id)
        subset_outcome = self._subset_outcome(policy, source)
        lifecycle_outcome = self._lifecycle_outcome(policy, now.astimezone(UTC))
        if lifecycle_outcome is not None:
            outcome = lifecycle_outcome
        elif subset_outcome is not None:
            outcome = subset_outcome
        else:
            outcome = CompilationOutcome.COMPILED_SIMULATION
        assert outcome is not None
        return CompiledApprovedSourcePolicy(
            policy_id=policy.policy_id,
            policy_version=policy.version,
            source_id=policy.source_id,
            discovery_template_id=policy.discovery.template_id,
            policy_digest=policy_digest,
            registry_digest=registry_digest,
            capability_digest=capability_digest,
            outcome=outcome,
            # Phase 0 proves compatibility only. It never grants runtime authority.
            authorization_eligible=False,
        )

    def compile_all(
        self,
        contract: ApprovedSourcePolicies,
        registry: SourceRegistryData,
        *,
        now: datetime,
    ) -> tuple[CompiledApprovedSourcePolicy, ...]:
        return tuple(self.compile(policy, registry, now=now) for policy in contract.policies)

    def _subset_outcome(
        self, policy: ApprovedSourcePolicy, source: object
    ) -> CompilationOutcome | None:
        if source is None:
            return CompilationOutcome.REJECTED_SOURCE_NOT_FOUND
        source_lifecycle = getattr(source, "lifecycle", None)
        if source_lifecycle != "ACTIVE":
            return CompilationOutcome.REJECTED_SOURCE_NOT_ACTIVE
        base_url = getattr(source, "base_url", None)
        if not isinstance(base_url, str):
            return CompilationOutcome.REJECTED_REGISTRY_SUBSET
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != policy.authority.host
            or parsed.path != policy.authority.endpoint
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or parsed.query
            or parsed.fragment
            or policy.authority.transport != getattr(source, "transport", None)
            or policy.authority.action not in getattr(source, "soap_operation_allowlist", ())
        ):
            return CompilationOutcome.REJECTED_REGISTRY_SUBSET
        capability = self._capabilities.find(
            source_id=policy.source_id,
            transport=policy.authority.transport,
            host=policy.authority.host,
            endpoint=policy.authority.endpoint,
            action=policy.authority.action,
            access_mode_requirement=policy.access_mode_requirement,
            discovery_mode=policy.discovery.mode,
            template_id=policy.discovery.template_id,
        )
        if capability is None:
            return CompilationOutcome.REJECTED_CAPABILITY
        policy_content_types = {
            *policy.constraints.content.content_types.allow,
            *policy.constraints.content.content_types.deny,
        }
        if not policy_content_types <= set(capability.allowed_content_types):
            return CompilationOutcome.REJECTED_CAPABILITY
        if not set(policy.constraints.content.parser_profiles) <= set(capability.parser_profiles):
            return CompilationOutcome.REJECTED_CAPABILITY
        if (
            capability.requires_exact_document_numbers
            and not policy.discovery.exact_document_numbers
        ):
            return CompilationOutcome.REJECTED_CAPABILITY
        if getattr(source, "access_mode", None) != policy.access_mode_requirement:
            return CompilationOutcome.ACTIVATION_BLOCKED_REGISTRY_ACCESS_MODE
        return None

    @staticmethod
    def _lifecycle_outcome(
        policy: ApprovedSourcePolicy, now: datetime
    ) -> CompilationOutcome | None:
        if policy.revoked:
            return CompilationOutcome.POLICY_REVOKED
        if policy.status is PolicyStatus.REVOKED:
            return CompilationOutcome.POLICY_REVOKED
        if policy.status is PolicyStatus.EXPIRED:
            return CompilationOutcome.POLICY_EXPIRED
        if policy.status is PolicyStatus.DRAFT:
            return CompilationOutcome.POLICY_DRAFT
        if policy.status is PolicyStatus.SUSPENDED:
            return CompilationOutcome.POLICY_SUSPENDED
        if not policy.effective_from <= now <= policy.effective_to:
            return CompilationOutcome.POLICY_EXPIRED
        return None
