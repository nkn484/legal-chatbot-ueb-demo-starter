"""Metadata checks for the append-only reviewed legal-effect registry."""

from pathlib import Path
from typing import cast

from sqlalchemy import CHAR, Boolean, CheckConstraint, DateTime, String, Table, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from legal_chatbot.db.base import Base
from legal_chatbot.documents.orm import (
    ReviewedLegalEffectAssertion,
    ReviewedLegalEffectEvent,
    ReviewedLegalEffectFamily,
    ReviewedLegalEffectImport,
)


def _check_expressions(table_name: str) -> set[str]:
    return {
        constraint.sqltext.text
        for constraint in Base.metadata.tables[table_name].constraints
        if isinstance(constraint, CheckConstraint)
    }


def test_reviewed_legal_effect_registry_tables_and_import_shadow_gate_are_declared() -> None:
    expected_tables = {
        "reviewed_legal_effect_imports",
        "reviewed_legal_effect_families",
        "reviewed_legal_effect_assertions",
        "reviewed_legal_effect_events",
    }
    assert expected_tables <= set(Base.metadata.tables)

    imports = cast(Table, ReviewedLegalEffectImport.__table__)
    assert set(imports.columns.keys()) == {
        "import_id",
        "artifact_sha256",
        "schema_version",
        "submitted_by",
        "submitted_at",
        "reviewed_by",
        "reviewed_at",
        "reviewer_role",
        "approved_by",
        "approved_at",
        "approver_role",
        "imported_at",
        "imported_by",
        "runtime_enabled",
    }
    assert isinstance(imports.c.artifact_sha256.type, CHAR)
    assert isinstance(imports.c.runtime_enabled.type, Boolean)
    assert imports.c.runtime_enabled.server_default is not None
    timestamp_columns = ("submitted_at", "reviewed_at", "approved_at", "imported_at")
    for column in timestamp_columns:
        timestamp_type = imports.c[column].type
        assert isinstance(timestamp_type, DateTime)
        assert timestamp_type.timezone
    assert any(
        set(constraint.columns.keys()) == {"artifact_sha256"}
        for constraint in imports.constraints
        if isinstance(constraint, UniqueConstraint)
    )
    assert _check_expressions(imports.name) >= {
        "artifact_sha256 ~ '^[0-9a-f]{64}$'",
        "reviewer_role = 'LEGAL_REVIEWER'",
        "approver_role = 'LEGAL_APPROVER'",
        "runtime_enabled = false",
        "submitted_at <= reviewed_at AND reviewed_at <= approved_at AND approved_at <= imported_at",
    }


def test_reviewed_legal_effect_family_and_assertion_evidence_anchors_are_declared() -> None:
    families = cast(Table, ReviewedLegalEffectFamily.__table__)
    assertions = cast(Table, ReviewedLegalEffectAssertion.__table__)

    assert set(families.columns.keys()) == {
        "import_id",
        "family_id",
        "completeness",
        "scope_note",
        "created_at",
    }
    assert isinstance(families.c.scope_note.type, String)
    assert families.c.scope_note.type.length == 500
    assert _check_expressions(families.name) >= {
        "completeness IN ('DECLARED_PARTIAL', 'DECLARED_COMPLETE')",
        "btrim(scope_note) <> '' AND scope_note !~ '[[:cntrl:]]'",
    }
    assert {
        foreign_key.parent.name: (foreign_key.target_fullname, foreign_key.ondelete)
        for foreign_key in families.foreign_keys
    } == {
        "import_id": ("reviewed_legal_effect_imports.import_id", "RESTRICT"),
    }

    assert set(assertions.columns.keys()) == {
        "assertion_id",
        "import_id",
        "family_id",
        "subject_document_version_id",
        "object_document_version_id",
        "relation_kind",
        "effect_state",
        "basis_document_version_id",
        "basis_source_provenance_record_id",
        "basis_locator_type",
        "basis_locator_value",
        "reviewed_by",
        "reviewed_at",
        "approved_by",
        "approved_at",
        "created_at",
    }
    assert all(
        isinstance(assertions.c[column].type, UUID)
        for column in (
            "subject_document_version_id",
            "object_document_version_id",
            "basis_document_version_id",
            "basis_source_provenance_record_id",
        )
    )
    assert _check_expressions(assertions.name) >= {
        "subject_document_version_id <> object_document_version_id",
        "relation_kind IN ('IMPLEMENTS', 'GOVERNS')",
        "effect_state = 'EFFECT_NOT_MODELED'",
        "basis_locator_type IN ('ARTICLE', 'CLAUSE', 'SECTION', 'PAGE')",
        "btrim(basis_locator_value) <> ''",
        "reviewed_at <= approved_at AND approved_at <= created_at",
    }
    assert {
        foreign_key.parent.name: (foreign_key.target_fullname, foreign_key.ondelete)
        for foreign_key in assertions.foreign_keys
        if foreign_key.parent.name not in {"import_id", "family_id"}
    } == {
        "subject_document_version_id": ("document_versions.id", "RESTRICT"),
        "object_document_version_id": ("document_versions.id", "RESTRICT"),
        "basis_document_version_id": ("document_versions.id", "RESTRICT"),
        "basis_source_provenance_record_id": ("source_provenance_records.id", "RESTRICT"),
    }
    family_foreign_key = next(
        foreign_key_constraint
        for foreign_key_constraint in assertions.foreign_key_constraints
        if set(foreign_key_constraint.column_keys) == {"import_id", "family_id"}
    )
    assert family_foreign_key.ondelete == "RESTRICT"
    assert {index.name for index in assertions.indexes} == {
        "ix_reviewed_legal_effect_assertions_subject_version",
        "ix_reviewed_legal_effect_assertions_object_version",
        "ix_reviewed_legal_effect_assertions_family",
        "ix_reviewed_legal_effect_assertions_relation_kind",
        "ix_reviewed_legal_effect_assertions_basis_provenance",
    }


def test_reviewed_legal_effect_event_shape_and_indexes_are_declared() -> None:
    events = cast(Table, ReviewedLegalEffectEvent.__table__)

    assert set(events.columns.keys()) == {
        "event_id",
        "assertion_id",
        "event_kind",
        "successor_assertion_id",
        "reason_code",
        "reason_note",
        "reviewed_by",
        "reviewed_at",
        "approved_by",
        "approved_at",
        "created_at",
    }
    assert events.c.successor_assertion_id.nullable
    assert not events.c.assertion_id.nullable
    assert isinstance(events.c.reason_note.type, String)
    assert events.c.reason_note.type.length == 500
    assert _check_expressions(events.name) >= {
        "event_kind IN ('CORRECTS', 'REVOKES')",
        "reason_code IN ('ENDPOINT_NOT_FOUND', 'VERSION_HASH_MISMATCH', "
        "'PROVENANCE_NOT_FOUND', 'LOCATOR_INVALID', 'DUPLICATE_ASSERTION', "
        "'FAMILY_SCOPE_CONFLICT', 'REVIEW_DISAGREEMENT', "
        "'SUPERSEDED_BY_REVIEW', 'WITHDRAWN_BY_REVIEW')",
        "(event_kind = 'CORRECTS' AND successor_assertion_id IS NOT NULL) OR "
        "(event_kind = 'REVOKES' AND successor_assertion_id IS NULL)",
        "successor_assertion_id IS NULL OR successor_assertion_id <> assertion_id",
        "reviewed_at <= approved_at AND approved_at <= created_at",
    }
    assert {index.name for index in events.indexes} == {
        "ix_reviewed_legal_effect_events_assertion",
        "ix_reviewed_legal_effect_events_successor",
        "ix_reviewed_legal_effect_events_event_kind",
    }


def test_registry_migration_is_head_successor_and_installs_append_only_triggers() -> None:
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0012_reviewed_legal_effects.py"
    )
    migration = migration_path.read_text(encoding="utf-8")

    assert 'revision = "0012_reviewed_legal_effects"' in migration
    assert 'down_revision = "0011_document_metadata_search"' in migration
    assert "CREATE FUNCTION reviewed_legal_effect_reject_mutation()" in migration
    assert "CREATE TRIGGER trg_{table_name}_append_only" in migration
    assert "DROP TRIGGER trg_{table_name}_append_only ON {table_name}" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "DROP FUNCTION reviewed_legal_effect_reject_mutation()" in migration
