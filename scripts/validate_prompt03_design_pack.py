"""Validate Prompt-03 documentation-pack structure without legal or runtime access."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
APPROVED_SCHEMA_PATH = ROOT / "contracts" / "reviewed-legal-effects-v1.schema.json"
REQUIRED_FILES = frozenset(
    {
        "prompt03-reviewed-legal-effects-inventory.md",
        "prompt03-reviewed-legal-effects-schema-proposal.md",
        "prompt03-reviewed-contract-draft.schema.json",
        "prompt03-verification-plan.md",
        "prompt03-approval-checklist.md",
        "prompt03-gate2-importer-runbook.md",
    }
)
URL_PATTERN = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)
UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
RAW_EVALUATION_FIELD_PATTERN = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?(?:question|answer|benchmark[ _-]?answer)\s*[:=]"
)
FORBIDDEN_CONTENT_FIELDS = frozenset({"question", "answer", "expected_answer", "chunk", "content"})
EXPECTED_INVENTORY_TOKENS = (
    "| Legal documents | 670 |",
    "672",
    "669",
    "661 / 670",
    "86 / 670",
    "1 / 670",
    "668",
    "2",
    "22",
    "26 distinct expert expected document families",
    "29 case occurrences",
)
REQUIRED_RUNBOOK_TOKENS = (
    "Gate-3: SYNTHETIC_SHADOW_VALIDATED",
    "| Database head | `0012` |",
    "four tables, 0 rows",
    "727 unit+compose PASS",
    "3 PostgreSQL integration PASS",
    "Lifecycle check | PASS",
    "Ruff | PASS",
    "Runtime/retrieval imports | none",
    "shape, enums, limits, and `additionalProperties` only",
    "semantic cross-record rules, reviewer/approver independence, timestamp order",
    "endpoint hash resolution, strict provenance/version linkage, stored locator match",
    "FKs, checks, `runtime_enabled=false`, and append-only UPDATE+DELETE triggers",
    "DB does **not** prevent unauthorized INSERT by itself",
    "Direct SQL/DML is unsupported and prohibited operationally",
    "INSERT only",
    "SELECT on evidence tables",
    "no UPDATE, no DELETE",
    "table-owner nor superuser capability",
    "HASH_PINNED_PILOT_ALLOWED",
    "REFRESH_REQUIRED",
    "`DECLARED_COMPLETE` applies only",
    "synthetic fixtures only",
    "SHADOW_DISABLED",
    "SHADOW_INPUT_REJECTED",
)
REQUIRED_GATE3_CLOSURE_TOKENS = (
    "7 actual disposable scenarios",
    "`SHADOW_ELIGIBLE` 2",
    "Restricted role checks | PASS",
    "retrieval/citation unchanged",
    "Main database registry | 0 rows",
    "733 unit+compose PASS",
    "temporary diagnostics only",
    "It is **not** legal applicability,\n"
    "authority, completeness, current effect, or answer eligibility.",
    "evaluator does not follow or validate a successor in another import/family",
    "distinct validated basis-provenance counts only",
    "synthetic/disposable only and never elevates evidence to official-source status",
    "no environment/runtime composition, retrieval\nimport, user-visible field, real artifact",
    "Final pre-real-artifact checklist",
    "Exact family semantics and declared scope",
    "Exact endpoint hashes, provenance, locators, and duplicate adjudication",
    "Production role grants and importer-only DML authority",
    "Shadow integration references, diagnostic retention, and main database import approval",
    "No routing effects are approved until a later gate",
    "No next implementation is authorized",
)


class ValidationError(ValueError):
    """Raised when the documentation-only Prompt-03 pack is structurally unsafe."""


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _walk(value: Any) -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            found.append((key, child))
            found.extend(_walk(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk(child))
    return found


def validate_design_pack(root: Path = ROOT) -> None:
    """Check static pack boundaries only; never validate legal truth or access services."""
    design_dir = root / "docs" / "design"
    missing = sorted(name for name in REQUIRED_FILES if not (design_dir / name).is_file())
    if missing:
        raise ValidationError(f"missing required files: {', '.join(missing)}")

    texts = {name: _read(design_dir / name) for name in REQUIRED_FILES}
    for name, text in texts.items():
        if URL_PATTERN.search(text):
            raise ValidationError(f"{name} contains a URL")
        if UUID_PATTERN.search(text):
            raise ValidationError(f"{name} contains a UUID")
        if RAW_EVALUATION_FIELD_PATTERN.search(text):
            raise ValidationError(f"{name} contains raw evaluation question or answer content")

    inventory = texts["prompt03-reviewed-legal-effects-inventory.md"]
    missing_tokens = [token for token in EXPECTED_INVENTORY_TOKENS if token not in inventory]
    if missing_tokens:
        raise ValidationError(f"inventory lacks verified token(s): {', '.join(missing_tokens)}")

    runbook = texts["prompt03-gate2-importer-runbook.md"]
    missing_runbook_tokens = [token for token in REQUIRED_RUNBOOK_TOKENS if token not in runbook]
    if missing_runbook_tokens:
        raise ValidationError(
            f"Gate-2 runbook lacks required token(s): {', '.join(missing_runbook_tokens)}"
        )
    missing_closure_tokens = [
        token for token in REQUIRED_GATE3_CLOSURE_TOKENS if token not in runbook
    ]
    if missing_closure_tokens:
        raise ValidationError(
            f"Gate-3 closure lacks required token(s): {', '.join(missing_closure_tokens)}"
        )
    for name in (
        "prompt03-reviewed-legal-effects-schema-proposal.md",
        "prompt03-verification-plan.md",
        "prompt03-approval-checklist.md",
    ):
        if "Gate-3: SYNTHETIC_SHADOW_VALIDATED" not in texts[name]:
            raise ValidationError(f"{name} must record Gate-3 synthetic shadow status")

    draft_schema = json.loads(texts["prompt03-reviewed-contract-draft.schema.json"])
    if not str(draft_schema.get("title", "")).startswith("HISTORICAL_DRAFT_NOT_APPROVED"):
        raise ValidationError("draft schema must be clearly marked historical")
    draft_properties = draft_schema.get("properties", {})
    if draft_properties.get("schema_version", {}).get("const") != "DRAFT_NOT_APPROVED-1":
        raise ValidationError("draft schema version is invalid")
    if draft_properties.get("profile_state", {}).get("const") != "DOCUMENTATION_ONLY_DEFAULT_OFF":
        raise ValidationError("draft schema must be documentation-only and default-off")

    for key, value in _walk(draft_schema):
        if key in FORBIDDEN_CONTENT_FIELDS:
            raise ValidationError(f"draft schema exposes forbidden raw-content field: {key}")
        if isinstance(value, str) and (URL_PATTERN.search(value) or UUID_PATTERN.search(value)):
            raise ValidationError("draft schema contains URL or UUID content")

    approved_path = root / "contracts" / APPROVED_SCHEMA_PATH.name
    if not approved_path.is_file():
        raise ValidationError("approved v1 schema is missing")
    schema = json.loads(_read(approved_path))
    properties = schema.get("properties", {})
    if properties.get("schema_version", {}).get("const") != "reviewed-legal-effects-v1":
        raise ValidationError("approved schema version is invalid")
    if properties.get("profile_state", {}).get("const") != "APPROVED_SCHEMA_DEFAULT_OFF":
        raise ValidationError("approved schema must be default-off")
    if "runtime_enabled" in properties:
        raise ValidationError("approved schema must not expose a runtime-enable field")

    for key, value in _walk(schema):
        if key in FORBIDDEN_CONTENT_FIELDS:
            raise ValidationError(f"approved schema exposes forbidden raw-content field: {key}")
        if isinstance(value, str) and (URL_PATTERN.search(value) or UUID_PATTERN.search(value)):
            raise ValidationError("approved schema contains URL or UUID content")

    definitions = schema.get("$defs", {})
    for name in (
        "endpoint",
        "locator",
        "basis",
        "approval",
        "family",
        "relation",
        "correction_event",
    ):
        if definitions.get(name, {}).get("additionalProperties") is not False:
            raise ValidationError(f"approved schema {name} must set additionalProperties to false")
    endpoint_required = set(definitions["endpoint"].get("required", []))
    if endpoint_required != {
        "source_id",
        "external_id",
        "snapshot_sha256",
        "normalized_text_sha256",
    }:
        raise ValidationError("approved endpoint selector must use source/external/hash selectors")
    relation = definitions["relation"].get("properties", {})
    if relation.get("relation_kind", {}).get("enum") != ["IMPLEMENTS", "GOVERNS"]:
        raise ValidationError("approved schema contains unapproved relation kinds")
    if relation.get("effect_state", {}).get("const") != "EFFECT_NOT_MODELED":
        raise ValidationError("approved schema must not model temporal legal effect")
    locator = definitions["locator"].get("properties", {})
    if locator.get("kind", {}).get("enum") != ["ARTICLE", "CLAUSE", "SECTION", "PAGE"]:
        raise ValidationError("approved schema contains unapproved locator kinds")
    provenance = definitions["basis"].get("properties", {}).get("provenance_id", {})
    if provenance != {
        "type": "string",
        "format": "uuid",
        "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        "minLength": 36,
        "maxLength": 36,
    }:
        raise ValidationError("approved schema provenance ID must be a canonical UUID")
    event_properties = definitions["correction_event"].get("properties", {})
    if {"reviewed_by", "approved_by", "reviewed_at", "approved_at"} & set(event_properties):
        raise ValidationError("correction events must inherit global approval metadata")
    if event_properties.get("reason_code", {}).get("enum") != [
        "ENDPOINT_NOT_FOUND",
        "VERSION_HASH_MISMATCH",
        "PROVENANCE_NOT_FOUND",
        "LOCATOR_INVALID",
        "DUPLICATE_ASSERTION",
        "FAMILY_SCOPE_CONFLICT",
        "REVIEW_DISAGREEMENT",
        "SUPERSEDED_BY_REVIEW",
        "WITHDRAWN_BY_REVIEW",
    ]:
        raise ValidationError("approved schema correction reason codes are invalid")


def main() -> int:
    """Run the documentation-only static checks."""
    try:
        validate_design_pack()
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        print(f"Prompt-03 design-pack validation failed: {error}", file=sys.stderr)
        return 1
    print("Prompt-03 design-pack validation passed (documentation-only; no legal truth checked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
