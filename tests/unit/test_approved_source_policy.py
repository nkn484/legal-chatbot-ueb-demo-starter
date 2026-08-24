"""Phase 0 policy-compiler tests; pure simulation with no source or database calls."""

from __future__ import annotations

import ast
import copy
import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

import pytest

from legal_chatbot.sources.adapter_capabilities import (
    CURRENT_ADAPTER_CAPABILITIES,
    AdapterCapability,
    AdapterCapabilityTable,
)
from legal_chatbot.sources.approved_policy import (
    AllowDenyConstraint,
    ApprovedSourcePolicies,
    ApprovedSourcePolicyCompiler,
    CompilationOutcome,
    PolicyContractError,
    PolicyStatus,
    canonical_json_digest,
    load_approved_source_policies,
)
from legal_chatbot.sources.registry import load_registry

CONTRACT_PATH = Path("contracts/approved-source-policies.json")
REGISTRY_PATH = Path("contracts/source-registry.json")
NOW = datetime(2026, 8, 21, tzinfo=UTC)
LIMIT_MAXIMA = {
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


class CanonicalEnum(StrEnum):
    VALUE = "VALUE"


@dataclass(frozen=True)
class CanonicalSample:
    published_on: date
    observed_at: datetime
    status: CanonicalEnum
    items: tuple[object, ...]


def _contract_payload() -> dict[str, Any]:
    with CONTRACT_PATH.open(encoding="utf-8") as contract_file:
        return json.load(contract_file)


def _compiler() -> ApprovedSourcePolicyCompiler:
    return ApprovedSourcePolicyCompiler(CURRENT_ADAPTER_CAPABILITIES)


def _simulated_matching_registry() -> object:
    registry = load_registry(REGISTRY_PATH)
    payload = registry.model_dump(mode="json")
    payload["systems"][0]["access_mode"] = "READ_ONLY_POLICY_ALLOWLIST"
    return type(registry).model_validate(payload)


def test_contract_fixtures_are_bounded_and_non_authorizing_under_current_registry() -> None:
    contract = load_approved_source_policies(CONTRACT_PATH)
    compiled = _compiler().compile_all(contract, load_registry(REGISTRY_PATH), now=NOW)

    assert [(item.policy_id, item.outcome, item.authorization_eligible) for item in compiled] == [
        ("vbqppl-exact-number-draft-v1", CompilationOutcome.POLICY_DRAFT, False),
        (
            "vbqppl-exact-number-registry-blocked-v1",
            CompilationOutcome.ACTIVATION_BLOCKED_REGISTRY_ACCESS_MODE,
            False,
        ),
    ]
    assert len(contract.policies) == 2
    assert [policy.status for policy in contract.policies] == [
        PolicyStatus.DRAFT,
        PolicyStatus.ACTIVE,
    ]


def test_matching_simulated_registry_compiles_without_runtime_authorization() -> None:
    policy = load_approved_source_policies(CONTRACT_PATH).policies[1]
    compiled = _compiler().compile(policy, _simulated_matching_registry(), now=NOW)  # type: ignore[arg-type]

    assert compiled.outcome is CompilationOutcome.COMPILED_SIMULATION
    assert compiled.authorization_eligible is False


def test_phase_zero_submodule_import_isolated_and_lazy_public_exports_resolve() -> None:
    source_path = str(Path("src").resolve())
    environment = os.environ | {
        "PYTHONPATH": source_path + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    isolated_import = """
import json
import sys
import legal_chatbot.sources.approved_policy

prohibited = (
    "httpx",
    "legal_chatbot.sources.adapters",
    "legal_chatbot.sources.port",
    "legal_chatbot.sources.registry",
    "legal_chatbot.sources.config",
    "legal_chatbot.sources.settings",
    "legal_chatbot.ingestion",
    "legal_chatbot.retrieval",
    "legal_chatbot.documents",
    "legal_chatbot.chat",
    "legal_chatbot.runtime",
    "legal_chatbot.providers",
    "legal_chatbot.channels",
    "sqlalchemy",
    "asyncpg",
)
loaded = [
    module
    for module in sys.modules
    for prefix in prohibited
    if module == prefix or module.startswith(prefix + ".")
]
print(json.dumps(sorted(loaded)))
"""
    result = subprocess.run(
        [sys.executable, "-c", isolated_import],
        check=True,
        capture_output=True,
        env=environment,
        text=True,
    )
    assert json.loads(result.stdout) == []

    lazy_exports = """
from legal_chatbot.sources import (
    LegalDocumentSnapshot,
    SourceSettings,
    discovery_cli,
    load_registry,
)

assert LegalDocumentSnapshot.__name__ == "LegalDocumentSnapshot"
assert SourceSettings.__name__ == "SourceSettings"
assert callable(load_registry)
assert discovery_cli.__name__ == "legal_chatbot.sources.discovery_cli"
"""
    subprocess.run(
        [sys.executable, "-c", lazy_exports],
        check=True,
        capture_output=True,
        env=environment,
        text=True,
    )


def test_canonical_digest_normalizes_dataclasses_dates_datetimes_enums_and_key_order() -> None:
    first = CanonicalSample(
        published_on=date(2026, 8, 21),
        observed_at=datetime(2026, 8, 21, 7, 30, tzinfo=timezone(timedelta(hours=7))),
        status=CanonicalEnum.VALUE,
        items=(True, None, {"z": 2, "a": "value"}),
    )
    second = {
        "items": [True, None, {"a": "value", "z": 2}],
        "status": "VALUE",
        "observed_at": datetime(2026, 8, 21, 0, 30, tzinfo=UTC),
        "published_on": date(2026, 8, 21),
    }

    assert canonical_json_digest(first) == canonical_json_digest(second)
    policy = load_approved_source_policies(CONTRACT_PATH).policies[1]
    assert canonical_json_digest(policy.canonical_data()) == canonical_json_digest(policy)


@pytest.mark.parametrize("value", [datetime(2026, 8, 21), object(), {"not-a-string-key": {1: "x"}}])
def test_canonical_digest_rejects_naive_datetimes_and_unsupported_values(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        canonical_json_digest(value)


@pytest.mark.parametrize(
    ("status", "revoked", "at", "expected"),
    [
        (PolicyStatus.DRAFT, False, NOW, CompilationOutcome.POLICY_DRAFT),
        (PolicyStatus.SUSPENDED, False, NOW, CompilationOutcome.POLICY_SUSPENDED),
        (PolicyStatus.EXPIRED, False, NOW, CompilationOutcome.POLICY_EXPIRED),
        (PolicyStatus.REVOKED, True, NOW, CompilationOutcome.POLICY_REVOKED),
        (PolicyStatus.ACTIVE, True, NOW, CompilationOutcome.POLICY_REVOKED),
        (
            PolicyStatus.ACTIVE,
            False,
            datetime(2027, 1, 1, tzinfo=UTC),
            CompilationOutcome.POLICY_EXPIRED,
        ),
    ],
)
def test_lifecycle_precedes_registry_and_is_non_authorizing(
    status: PolicyStatus,
    revoked: bool,
    at: datetime,
    expected: CompilationOutcome,
) -> None:
    policy = replace(
        load_approved_source_policies(CONTRACT_PATH).policies[1], status=status, revoked=revoked
    )
    compiled = _compiler().compile(policy, load_registry(REGISTRY_PATH), now=at)

    assert compiled.outcome is expected
    assert not compiled.authorization_eligible


def test_explicit_revoked_status_requires_revocation_and_revisions_are_immutable() -> None:
    payload = _contract_payload()
    payload["policies"][0]["status"] = "REVOKED"
    with pytest.raises(PolicyContractError, match="requires revoked"):
        ApprovedSourcePolicies.from_data(payload)

    payload = _contract_payload()
    payload["policies"].append(copy.deepcopy(payload["policies"][0]))
    with pytest.raises(PolicyContractError, match="duplicated"):
        ApprovedSourcePolicies.from_data(payload)

    payload = _contract_payload()
    payload["policies"][0]["status"] = "EXPIRED"
    assert ApprovedSourcePolicies.from_data(payload).policies[0].status is PolicyStatus.EXPIRED

    payload = _contract_payload()
    payload["policies"][0]["status"] = "REVOKED"
    payload["policies"][0]["revocation"] = {
        "status": "REVOKED",
        "reason_code": "GOVERNANCE_REVOKED",
    }
    assert ApprovedSourcePolicies.from_data(payload).policies[0].status is PolicyStatus.REVOKED

    payload = _contract_payload()
    payload["policies"][1]["policy_id"] = payload["policies"][0]["policy_id"]
    payload["policies"][1]["version"] = 2
    assert [policy.version for policy in ApprovedSourcePolicies.from_data(payload).policies] == [
        1,
        2,
    ]


@pytest.mark.parametrize(
    ("mutator", "expected"),
    [
        (
            lambda payload: payload["policies"][1].update({"source_id": "FUTURE_SOURCE"}),
            CompilationOutcome.REJECTED_SOURCE_NOT_FOUND,
        ),
        (
            lambda payload: payload["policies"][1]["authority"].update({"host": "future.example"}),
            CompilationOutcome.REJECTED_REGISTRY_SUBSET,
        ),
        (
            lambda payload: payload["policies"][1]["authority"].update(
                {"endpoint": "/future.asmx"}
            ),
            CompilationOutcome.REJECTED_REGISTRY_SUBSET,
        ),
        (
            lambda payload: payload["policies"][1]["authority"].update({"action": "FutureAction"}),
            CompilationOutcome.REJECTED_REGISTRY_SUBSET,
        ),
        (
            lambda payload: payload["policies"][1].update(
                {"access_mode_requirement": "FUTURE_ACCESS_MODE"}
            ),
            CompilationOutcome.REJECTED_CAPABILITY,
        ),
        (
            lambda payload: payload["policies"][1]["discovery"].update(
                {"template_id": "future_template_v1"}
            ),
            CompilationOutcome.REJECTED_CAPABILITY,
        ),
        (
            lambda payload: payload["policies"][1]["constraints"]["content"].update(
                {"allow_content_types": ["application/xml"]}
            ),
            CompilationOutcome.REJECTED_CAPABILITY,
        ),
        (
            lambda payload: payload["policies"][1]["constraints"]["content"].update(
                {"parser_profiles": ["FUTURE_XML_V1"]}
            ),
            CompilationOutcome.REJECTED_CAPABILITY,
        ),
    ],
)
def test_unknown_syntactically_valid_values_load_then_fail_closed_in_compiler(
    mutator: Callable[[dict[str, Any]], None], expected: CompilationOutcome
) -> None:
    payload = _contract_payload()
    mutator(payload)
    policy = ApprovedSourcePolicies.from_data(payload).policies[1]
    compiled = _compiler().compile(policy, _simulated_matching_registry(), now=NOW)  # type: ignore[arg-type]

    assert compiled.outcome is expected
    assert compiled.authorization_eligible is False


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload["policies"][0]["tls"].update({"verify": False}),
        lambda payload: payload["policies"][0]["authority"].update({"host": "*.vbpl.vn"}),
        lambda payload: payload["policies"][0]["authority"].update({"host": "https://ws.vbpl.vn"}),
        lambda payload: payload["policies"][0]["authority"].update({"endpoint": "/vbqppl.*"}),
        lambda payload: payload["policies"][0]["discovery"].update({"mode": "FIXED.*"}),
        lambda payload: payload["policies"][0]["discovery"].update({"template_id": "future.*"}),
        lambda payload: payload["policies"][0]["discovery"].update(
            {"exact_document_numbers": [f"{index}/2026/QH16" for index in range(9)]}
        ),
        lambda payload: payload["policies"][0]["constraints"]["titles"].update({"allow": [".*"]}),
        lambda payload: payload["policies"][0]["constraints"]["paths"].update(
            {"allow": ["/qtdc/.*/"]}
        ),
        lambda payload: payload["policies"][0]["constraints"]["issuers"].update({"allow": []}),
        lambda payload: payload["policies"][0]["constraints"]["jurisdictions"].update(
            {"allow": []}
        ),
        lambda payload: payload["policies"][0]["constraints"]["document_types"].update(
            {"allow": ["LAW", "LAW"]}
        ),
        lambda payload: payload["policies"][0]["constraints"]["date_range"].update(
            {"from": "2000-01-01", "to": "2026-12-31"}
        ),
    ],
)
def test_broad_unsafe_or_unbounded_contract_fields_are_rejected(
    mutator: Callable[[dict[str, Any]], None],
) -> None:
    payload = copy.deepcopy(_contract_payload())
    mutator(payload)

    with pytest.raises(PolicyContractError):
        ApprovedSourcePolicies.from_data(payload)


@pytest.mark.parametrize("limit_name", tuple(LIMIT_MAXIMA))
@pytest.mark.parametrize("value_kind", ("zero", "over_max"))
def test_each_limit_rejects_zero_and_its_specific_maximum(limit_name: str, value_kind: str) -> None:
    payload = _contract_payload()
    payload["policies"][0]["limits"][limit_name] = (
        0 if value_kind == "zero" else LIMIT_MAXIMA[limit_name] + 1
    )

    with pytest.raises(PolicyContractError):
        ApprovedSourcePolicies.from_data(payload)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda limits: limits.update(
            {"max_calls_per_request": 2, "max_calls_per_policy_window": 1}
        ),
        lambda limits: limits.update(
            {"max_documents_per_request": 2, "max_results_per_discovery": 1}
        ),
        lambda limits: limits.update(
            {"max_results_per_discovery": 9, "max_calls_per_policy_window": 8}
        ),
        lambda limits: limits.update(
            {"max_calls_per_policy_window": 9, "rate_limit_per_window": 8}
        ),
        lambda limits: limits.update({"request_timeout_seconds": 6, "max_elapsed_seconds": 5}),
    ],
)
def test_limit_cross_field_bounds_are_rejected(mutator: Callable[[dict[str, int]], None]) -> None:
    payload = _contract_payload()
    mutator(payload["policies"][0]["limits"])

    with pytest.raises(PolicyContractError):
        ApprovedSourcePolicies.from_data(payload)


def test_deny_conflict_audit_privacy_and_compiler_boundaries() -> None:
    payload = _contract_payload()
    payload["policies"][0]["constraints"]["document_types"] = {
        "allow": ["LAW"],
        "deny": ["LAW"],
    }
    with pytest.raises(PolicyContractError, match="conflict"):
        ApprovedSourcePolicies.from_data(payload)
    assert not AllowDenyConstraint(("LAW",), ("LAW",)).permits("LAW")

    compiled = _compiler().compile(
        load_approved_source_policies(CONTRACT_PATH).policies[1],
        load_registry(REGISTRY_PATH),
        now=NOW,
    )
    audit = compiled.audit_record(duration_ms=0)
    rendered = json.dumps(audit, sort_keys=True)
    assert set(audit) == {
        "policy_id",
        "policy_version",
        "source_id",
        "template_id",
        "outcome",
        "duration_ms",
        "authorization_eligible",
    }
    for prohibited in ("63/2025/QH15", "Tổ chức", "ws.vbpl.vn", "qtdc", ".*", "question"):
        assert prohibited not in rendered
    with pytest.raises(ValueError):
        compiled.audit_record(duration_ms=-1)
    assert not hasattr(compiled, "fetch_ref")
    assert not hasattr(compiled, "grant")

    with pytest.raises(ValueError, match="bounded"):
        replace(CURRENT_ADAPTER_CAPABILITIES.capabilities[0], allowed_content_types=())
    with pytest.raises(ValueError, match="invalid"):
        AdapterCapabilityTable(version=2, capabilities=CURRENT_ADAPTER_CAPABILITIES.capabilities)

    future_capability = replace(
        CURRENT_ADAPTER_CAPABILITIES.capabilities[0],
        discovery_mode="FIXED_OFFICIAL_INDEX",
        template_id="future_template_v1",
        allowed_content_types=("application/xml",),
        parser_profiles=("FUTURE_XML_V1",),
        requires_exact_document_numbers=False,
    )
    assert isinstance(future_capability, AdapterCapability)
    future_capabilities = AdapterCapabilityTable(
        version=1,
        capabilities=(*CURRENT_ADAPTER_CAPABILITIES.capabilities, future_capability),
    )
    payload = _contract_payload()
    payload["policies"][1]["discovery"]["mode"] = "FIXED_OFFICIAL_INDEX"
    payload["policies"][1]["discovery"]["template_id"] = "future_template_v1"
    payload["policies"][1]["discovery"]["exact_document_numbers"] = []
    payload["policies"][1]["constraints"]["content"] = {
        "allow_content_types": ["application/xml"],
        "deny_content_types": [],
        "max_decoded_bytes": 1048576,
        "parser_profiles": ["FUTURE_XML_V1"],
    }
    future_policy = ApprovedSourcePolicies.from_data(payload).policies[1]
    future_compiled = ApprovedSourcePolicyCompiler(future_capabilities).compile(
        future_policy,
        _simulated_matching_registry(),  # type: ignore[arg-type]
        now=NOW,
    )
    assert future_compiled.outcome is CompilationOutcome.COMPILED_SIMULATION
    assert future_compiled.authorization_eligible is False

    payload = _contract_payload()
    payload["policies"][1]["discovery"]["exact_document_numbers"] = []
    exact_number_policy = ApprovedSourcePolicies.from_data(payload).policies[1]
    exact_number_compiled = _compiler().compile(
        exact_number_policy,
        _simulated_matching_registry(),  # type: ignore[arg-type]
        now=NOW,
    )
    assert exact_number_compiled.outcome is CompilationOutcome.REJECTED_CAPABILITY
    assert exact_number_compiled.authorization_eligible is False

    prohibited_imports = {
        "httpx",
        "adapters",
        "chat",
        "retrieval",
        "ingestion",
        "documents",
        "runtime",
        "providers",
        "channels",
        "sqlalchemy",
        "asyncpg",
    }
    for path in (
        Path("src/legal_chatbot/sources/approved_policy.py"),
        Path("src/legal_chatbot/sources/adapter_capabilities.py"),
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported_parts = {
            part
            for node in ast.walk(tree)
            for imported_name in (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module]
                if isinstance(node, ast.ImportFrom) and node.module
                else []
            )
            for part in imported_name.split(".")
        }
        assert not imported_parts & prohibited_imports
