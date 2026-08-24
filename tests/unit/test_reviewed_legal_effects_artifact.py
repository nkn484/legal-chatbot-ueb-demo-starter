from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from legal_chatbot.legal_effects import (
    LegalEffectsArtifactError,
    LegalEffectsErrorCode,
    canonical_artifact_bytes,
    canonical_artifact_sha256,
    parse_reviewed_legal_effects_artifact,
)
from legal_chatbot.legal_effects.constants import MAX_ARTIFACT_BYTES

SYNTHETIC_PROVENANCE_ID = UUID("00000000-0000-4000-8000-000000000001")


def _sha(character: str) -> str:
    return character * 64


def _endpoint(external_id: str, snapshot_character: str, text_character: str) -> dict[str, str]:
    return {
        "source_id": "UEB",
        "external_id": external_id,
        "snapshot_sha256": _sha(snapshot_character),
        "normalized_text_sha256": _sha(text_character),
    }


def artifact_payload() -> dict[str, Any]:
    subject = _endpoint("synthetic-subject", "a", "b")
    object_endpoint = _endpoint("synthetic-object", "c", "d")
    return {
        "schema_version": "reviewed-legal-effects-v1",
        "profile_state": "APPROVED_SCHEMA_DEFAULT_OFF",
        "artifact_id": "synthetic-artifact",
        "approval": {
            "submitted_by": "submitter",
            "submitted_at": "2026-08-24T09:00:00Z",
            "reviewer_role": "LEGAL_REVIEWER",
            "reviewed_by": "reviewer",
            "reviewed_at": "2026-08-24T10:00:00Z",
            "approver_role": "LEGAL_APPROVER",
            "approved_by": "approver",
            "approved_at": "2026-08-24T11:00:00Z",
        },
        "families": [
            {
                "family_id": "synthetic-family",
                "completeness": "DECLARED_PARTIAL",
                "scope_note": "Synthetic fixture scope only.",
            }
        ],
        "relations": [
            {
                "relation_id": "synthetic-relation-one",
                "family_id": "synthetic-family",
                "subject": subject,
                "object": object_endpoint,
                "relation_kind": "IMPLEMENTS",
                "effect_state": "EFFECT_NOT_MODELED",
                "basis": {
                    "endpoint": subject,
                    "provenance_id": str(SYNTHETIC_PROVENANCE_ID),
                    "locator": {"kind": "ARTICLE", "value": "Article synthetic"},
                },
            }
        ],
    }


def parse_payload(payload: dict[str, Any] | None = None):
    return parse_reviewed_legal_effects_artifact(payload or artifact_payload())


def test_parser_returns_frozen_validated_artifact_and_stable_canonical_hash() -> None:
    first = parse_payload()
    second_payload = artifact_payload()
    reordered = json.dumps(
        second_payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    second = parse_reviewed_legal_effects_artifact(reordered)
    from_bytes = parse_reviewed_legal_effects_artifact(reordered.encode("utf-8"))

    assert isinstance(first.families, tuple)
    assert canonical_artifact_bytes(first) == canonical_artifact_bytes(second)
    assert canonical_artifact_sha256(first) == canonical_artifact_sha256(second)
    assert canonical_artifact_sha256(first) == canonical_artifact_sha256(from_bytes)
    serialized = first.model_dump(mode="json")
    assert serialized["relations"][0]["basis"]["provenance_id"] == str(SYNTHETIC_PROVENANCE_ID)
    assert str(SYNTHETIC_PROVENANCE_ID) not in repr(first)
    assert "snapshot_sha256" not in repr(first)
    with pytest.raises(ValidationError):
        first.artifact_id = "changed"  # type: ignore[misc]


def test_parser_rejects_oversized_duplicate_and_extra_input_without_data_leakage() -> None:
    oversized = " " * (MAX_ARTIFACT_BYTES + 1)
    with pytest.raises(LegalEffectsArtifactError) as oversized_error:
        parse_reviewed_legal_effects_artifact(oversized)
    assert oversized_error.value.code is LegalEffectsErrorCode.ARTIFACT_TOO_LARGE

    duplicate_json = '{"schema_version":"x","schema_version":"y"}'
    with pytest.raises(LegalEffectsArtifactError) as duplicate_error:
        parse_reviewed_legal_effects_artifact(duplicate_json)
    assert duplicate_error.value.code is LegalEffectsErrorCode.DUPLICATE_JSON_KEY

    payload = artifact_payload()
    payload["question"] = "sensitive fixture content"
    with pytest.raises(LegalEffectsArtifactError) as invalid_error:
        parse_payload(payload)
    assert invalid_error.value.code is LegalEffectsErrorCode.INVALID_ARTIFACT
    assert "sensitive fixture content" not in str(invalid_error.value)
    assert "sensitive fixture content" not in repr(invalid_error.value)


def test_parser_does_not_expose_invalid_provenance_uuid() -> None:
    payload = artifact_payload()
    invalid_provenance_id = "00000000-0000-4000-8000-0000000000AA"
    payload["relations"][0]["basis"]["provenance_id"] = invalid_provenance_id

    with pytest.raises(LegalEffectsArtifactError) as error:
        parse_payload(payload)
    assert error.value.code is LegalEffectsErrorCode.INVALID_ARTIFACT
    assert invalid_provenance_id not in str(error.value)
    assert invalid_provenance_id not in repr(error.value)


def test_parser_rejects_unapproved_correction_reason_code() -> None:
    payload = artifact_payload()
    payload["events"] = [
        {
            "event_id": "synthetic-event",
            "assertion_id": "prior-import-relation",
            "kind": "REVOKES",
            "reason_code": "UNAPPROVED_REASON",
            "reason_note": "Synthetic fixture only.",
        }
    ]

    with pytest.raises(LegalEffectsArtifactError, match="invalid_artifact"):
        parse_payload(payload)


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (
            lambda payload: payload["relations"][0].update({"family_id": "unknown-family"}),
            LegalEffectsErrorCode.INVALID_ARTIFACT,
        ),
        (
            lambda payload: payload["approval"].update({"approved_by": "reviewer"}),
            LegalEffectsErrorCode.INVALID_ARTIFACT,
        ),
        (
            lambda payload: payload["approval"].update({"reviewed_at": "2026-08-24T08:00:00Z"}),
            LegalEffectsErrorCode.INVALID_ARTIFACT,
        ),
        (
            lambda payload: payload["relations"][0].update({"relation_kind": "AMENDS"}),
            LegalEffectsErrorCode.INVALID_ARTIFACT,
        ),
        (
            lambda payload: payload["relations"][0].update({"effective_from": "2026-01-01"}),
            LegalEffectsErrorCode.INVALID_ARTIFACT,
        ),
        (
            lambda payload: payload["relations"][0]["basis"]["locator"].update(
                {"value": "https://unsafe.example"}
            ),
            LegalEffectsErrorCode.INVALID_ARTIFACT,
        ),
        (
            lambda payload: payload["relations"][0]["basis"]["locator"].update(
                {"kind": "OTHER_PINPOINT"}
            ),
            LegalEffectsErrorCode.INVALID_ARTIFACT,
        ),
        (
            lambda payload: payload["relations"][0]["basis"].update(
                {"provenance_id": "00000000-0000-4000-8000-0000000000AA"}
            ),
            LegalEffectsErrorCode.INVALID_ARTIFACT,
        ),
        (
            lambda payload: payload["families"][0].update({"scope_note": "bad\ncontrol"}),
            LegalEffectsErrorCode.INVALID_ARTIFACT,
        ),
        (
            lambda payload: payload["relations"][0]["basis"]["locator"].update(
                {"value": "bad\u202eformat"}
            ),
            LegalEffectsErrorCode.INVALID_ARTIFACT,
        ),
    ],
)
def test_parser_rejects_unapproved_or_unsafe_artifact_shapes(mutate, expected_code) -> None:
    payload = copy.deepcopy(artifact_payload())
    mutate(payload)

    with pytest.raises(LegalEffectsArtifactError) as error:
        parse_payload(payload)
    assert error.value.code is expected_code


def test_parser_rejects_invalid_endpoint_relation_and_event_references() -> None:
    same_endpoints = artifact_payload()
    same_endpoints["relations"][0]["object"] = same_endpoints["relations"][0]["subject"]
    with pytest.raises(LegalEffectsArtifactError, match="invalid_artifact"):
        parse_payload(same_endpoints)

    duplicate_relation = artifact_payload()
    duplicate_relation["relations"].append(copy.deepcopy(duplicate_relation["relations"][0]))
    duplicate_relation["relations"][1]["relation_id"] = "synthetic-relation-two"
    with pytest.raises(LegalEffectsArtifactError, match="invalid_artifact"):
        parse_payload(duplicate_relation)

    invalid_event = artifact_payload()
    invalid_event["events"] = [
        {
            "event_id": "synthetic-event",
            "assertion_id": "synthetic-relation-one",
            "kind": "CORRECTS",
            "reason_code": "REVIEW_DISAGREEMENT",
            "reason_note": "Synthetic fixture only.",
        }
    ]
    with pytest.raises(LegalEffectsArtifactError, match="invalid_artifact"):
        parse_payload(invalid_event)

    prior_import_event = artifact_payload()
    prior_import_event["events"] = [
        {
            "event_id": "synthetic-event",
            "assertion_id": "prior-import-relation",
            "kind": "REVOKES",
            "reason_code": "WITHDRAWN_BY_REVIEW",
            "reason_note": "Synthetic fixture only.",
        }
    ]
    artifact = parse_payload(prior_import_event)
    assert artifact.events[0].assertion_id == "prior-import-relation"

    invalid_successor = artifact_payload()
    invalid_successor["events"] = [
        {
            "event_id": "synthetic-event",
            "assertion_id": "prior-import-relation",
            "kind": "CORRECTS",
            "successor_relation_id": "missing-current-relation",
            "reason_code": "SUPERSEDED_BY_REVIEW",
            "reason_note": "Synthetic fixture only.",
        }
    ]
    with pytest.raises(LegalEffectsArtifactError, match="invalid_artifact"):
        parse_payload(invalid_successor)


def test_parser_accepts_correction_event_that_inherits_global_approval() -> None:
    payload = artifact_payload()
    replacement = copy.deepcopy(payload["relations"][0])
    replacement["relation_id"] = "synthetic-relation-two"
    replacement["subject"] = _endpoint("synthetic-third", "e", "f")
    payload["relations"].append(replacement)
    payload["events"] = [
        {
            "event_id": "synthetic-event",
            "assertion_id": "synthetic-relation-one",
            "kind": "CORRECTS",
            "successor_relation_id": "synthetic-relation-two",
            "reason_code": "SUPERSEDED_BY_REVIEW",
            "reason_note": "Synthetic correction fixture only.",
        }
    ]

    artifact = parse_payload(payload)
    assert artifact.events[0].successor_relation_id == "synthetic-relation-two"


def test_approved_schema_parity_and_static_safety() -> None:
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "contracts"
        / "reviewed-legal-effects-v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    definitions = schema["$defs"]

    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["const"] == "reviewed-legal-effects-v1"
    assert schema["properties"]["profile_state"]["const"] == "APPROVED_SCHEMA_DEFAULT_OFF"
    assert "runtime_enabled" not in schema["properties"]
    assert definitions["endpoint"]["required"] == [
        "source_id",
        "external_id",
        "snapshot_sha256",
        "normalized_text_sha256",
    ]
    assert definitions["relation"]["properties"]["relation_kind"]["enum"] == [
        "IMPLEMENTS",
        "GOVERNS",
    ]
    assert definitions["locator"]["properties"]["kind"]["enum"] == [
        "ARTICLE",
        "CLAUSE",
        "SECTION",
        "PAGE",
    ]
    assert definitions["basis"]["properties"]["provenance_id"] == {
        "type": "string",
        "format": "uuid",
        "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        "minLength": 36,
        "maxLength": 36,
    }
    assert definitions["correction_event"]["properties"]["reason_code"]["enum"] == [
        "ENDPOINT_NOT_FOUND",
        "VERSION_HASH_MISMATCH",
        "PROVENANCE_NOT_FOUND",
        "LOCATOR_INVALID",
        "DUPLICATE_ASSERTION",
        "FAMILY_SCOPE_CONFLICT",
        "REVIEW_DISAGREEMENT",
        "SUPERSEDED_BY_REVIEW",
        "WITHDRAWN_BY_REVIEW",
    ]
    for name in (
        "endpoint",
        "locator",
        "basis",
        "approval",
        "family",
        "relation",
        "correction_event",
    ):
        assert definitions[name]["additionalProperties"] is False
