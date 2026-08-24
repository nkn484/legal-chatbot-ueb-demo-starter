"""Synthetic, database-free safety checks for the reviewed-effects importer."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from legal_chatbot.legal_effects import (
    LegalEffectsErrorCode,
    LegalEffectsImportError,
    ReviewedLegalEffectsImporter,
    parse_reviewed_legal_effects_artifact,
)
from legal_chatbot.legal_effects.importer import (
    ReviewedLegalEffectsImportResult,
    ReviewedLegalEffectsImportStatus,
)
from legal_chatbot.legal_effects.importer_cli import _result_payload
from legal_chatbot.legal_effects.validation import locator_matches


def _artifact():
    return parse_reviewed_legal_effects_artifact(
        {
            "schema_version": "reviewed-legal-effects-v1",
            "profile_state": "APPROVED_SCHEMA_DEFAULT_OFF",
            "artifact_id": "synthetic-import",
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
                    "scope_note": "Synthetic only.",
                }
            ],
            "relations": [
                {
                    "relation_id": "synthetic-relation",
                    "family_id": "synthetic-family",
                    "subject": {
                        "source_id": "UEB",
                        "external_id": "synthetic-subject",
                        "snapshot_sha256": "a" * 64,
                        "normalized_text_sha256": "b" * 64,
                    },
                    "object": {
                        "source_id": "UEB",
                        "external_id": "synthetic-object",
                        "snapshot_sha256": "c" * 64,
                        "normalized_text_sha256": "d" * 64,
                    },
                    "relation_kind": "IMPLEMENTS",
                    "effect_state": "EFFECT_NOT_MODELED",
                    "basis": {
                        "endpoint": {
                            "source_id": "UEB",
                            "external_id": "synthetic-subject",
                            "snapshot_sha256": "a" * 64,
                            "normalized_text_sha256": "b" * 64,
                        },
                        "provenance_id": "00000000-0000-4000-8000-000000000001",
                        "locator": {"kind": "ARTICLE", "value": "Article One"},
                    },
                }
            ],
        }
    )


@pytest.mark.asyncio
async def test_importer_rejects_unsafe_actor_and_future_approval_before_session_open() -> None:
    artifact = _artifact()

    def unused_session_factory():
        raise AssertionError("validation must occur before opening a session")

    importer = ReviewedLegalEffectsImporter(
        unused_session_factory, clock=lambda: datetime(2026, 8, 24, 10, 59, tzinfo=UTC)  # type: ignore[arg-type]
    )
    with pytest.raises(LegalEffectsImportError) as future_error:
        await importer.import_artifact(artifact, "operator")
    assert future_error.value.code is LegalEffectsErrorCode.APPROVAL_TIMESTAMP_FUTURE

    with pytest.raises(LegalEffectsImportError) as actor_error:
        await importer.import_artifact(artifact, "unsafe actor")
    assert actor_error.value.code is LegalEffectsErrorCode.INVALID_IMPORTED_BY
    assert "unsafe actor" not in str(actor_error.value)


def test_locator_matching_uses_only_normalized_structured_metadata() -> None:
    assert locator_matches(
        {"kind": "article", "label": "  ARTICLE\u00a0ONE "}, "ARTICLE", "article one"
    )
    assert locator_matches({"kind": "page", "value": " Page 2 "}, "PAGE", "page 2")
    assert not locator_matches({"kind": "article", "label": "Article One"}, "PAGE", "Article One")
    assert not locator_matches({"kind": "article"}, "ARTICLE", "Article One")


def test_cli_result_payload_is_content_free_and_reports_noop_insert_counts() -> None:
    payload = _result_payload(
        ReviewedLegalEffectsImportResult(
            status=ReviewedLegalEffectsImportStatus.ALREADY_IMPORTED,
            import_count=0,
            family_count=0,
            assertion_count=0,
            event_count=0,
            manual_basis_count=0,
            source_fetch_basis_count=0,
            artifact_hash_prefix="0123456789ab",
        )
    )
    assert payload == {
        "event": "reviewed_legal_effects_import",
        "status": "ALREADY_IMPORTED",
        "import_count": 0,
        "family_count": 0,
        "assertion_count": 0,
        "event_count": 0,
        "manual_basis_count": 0,
        "source_fetch_basis_count": 0,
        "artifact_hash_prefix": "0123456789ab",
    }
