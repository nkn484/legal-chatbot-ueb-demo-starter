"""Add the append-only, shadow-only reviewed legal-effect registry.

Revision ID: 0012_reviewed_legal_effects
Revises: 0011_document_metadata_search
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012_reviewed_legal_effects"
down_revision = "0011_document_metadata_search"
branch_labels = None
depends_on = None

_TABLES = (
    "reviewed_legal_effect_imports",
    "reviewed_legal_effect_families",
    "reviewed_legal_effect_assertions",
    "reviewed_legal_effect_events",
)


def upgrade() -> None:
    op.create_table(
        "reviewed_legal_effect_imports",
        sa.Column("import_id", sa.String(length=128), nullable=False),
        sa.Column("artifact_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("submitted_by", sa.String(length=128), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_by", sa.String(length=128), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewer_role", sa.String(length=32), nullable=False),
        sa.Column("approved_by", sa.String(length=128), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approver_role", sa.String(length=32), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("imported_by", sa.String(length=128), nullable=False),
        sa.Column("runtime_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint(
            "artifact_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_reviewed_legal_effect_imports_artifact_sha256",
        ),
        sa.CheckConstraint(
            "reviewer_role = 'LEGAL_REVIEWER'",
            name="ck_reviewed_legal_effect_imports_reviewer_role",
        ),
        sa.CheckConstraint(
            "approver_role = 'LEGAL_APPROVER'",
            name="ck_reviewed_legal_effect_imports_approver_role",
        ),
        sa.CheckConstraint(
            "runtime_enabled = false",
            name="ck_reviewed_legal_effect_imports_runtime_disabled",
        ),
        sa.CheckConstraint(
            "submitted_at <= reviewed_at AND reviewed_at <= approved_at "
            "AND approved_at <= imported_at",
            name="ck_reviewed_legal_effect_imports_timestamp_order",
        ),
        sa.PrimaryKeyConstraint("import_id"),
        sa.UniqueConstraint(
            "artifact_sha256", name="uq_reviewed_legal_effect_imports_artifact_sha256"
        ),
    )
    op.create_table(
        "reviewed_legal_effect_families",
        sa.Column("import_id", sa.String(length=128), nullable=False),
        sa.Column("family_id", sa.String(length=128), nullable=False),
        sa.Column("completeness", sa.String(length=32), nullable=False),
        sa.Column("scope_note", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "completeness IN ('DECLARED_PARTIAL', 'DECLARED_COMPLETE')",
            name="ck_reviewed_legal_effect_families_completeness",
        ),
        sa.CheckConstraint(
            "btrim(scope_note) <> '' AND scope_note !~ '[[:cntrl:]]'",
            name="ck_reviewed_legal_effect_families_scope_note_valid",
        ),
        sa.ForeignKeyConstraint(
            ["import_id"], ["reviewed_legal_effect_imports.import_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("import_id", "family_id"),
    )
    op.create_table(
        "reviewed_legal_effect_assertions",
        sa.Column("assertion_id", sa.String(length=128), nullable=False),
        sa.Column("import_id", sa.String(length=128), nullable=False),
        sa.Column("family_id", sa.String(length=128), nullable=False),
        sa.Column(
            "subject_document_version_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "object_document_version_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("relation_kind", sa.String(length=32), nullable=False),
        sa.Column("effect_state", sa.String(length=32), nullable=False),
        sa.Column("basis_document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "basis_source_provenance_record_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("basis_locator_type", sa.String(length=16), nullable=False),
        sa.Column("basis_locator_value", sa.String(length=500), nullable=False),
        sa.Column("reviewed_by", sa.String(length=128), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_by", sa.String(length=128), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "subject_document_version_id <> object_document_version_id",
            name="ck_reviewed_legal_effect_assertions_distinct_endpoints",
        ),
        sa.CheckConstraint(
            "relation_kind IN ('IMPLEMENTS', 'GOVERNS')",
            name="ck_reviewed_legal_effect_assertions_relation_kind",
        ),
        sa.CheckConstraint(
            "effect_state = 'EFFECT_NOT_MODELED'",
            name="ck_reviewed_legal_effect_assertions_effect_state",
        ),
        sa.CheckConstraint(
            "basis_locator_type IN ('ARTICLE', 'CLAUSE', 'SECTION', 'PAGE')",
            name="ck_reviewed_legal_effect_assertions_basis_locator_type",
        ),
        sa.CheckConstraint(
            "btrim(basis_locator_value) <> ''",
            name="ck_reviewed_legal_effect_assertions_basis_locator_value",
        ),
        sa.CheckConstraint(
            "reviewed_at <= approved_at AND approved_at <= created_at",
            name="ck_reviewed_legal_effect_assertions_timestamp_order",
        ),
        sa.ForeignKeyConstraint(
            ["import_id", "family_id"],
            [
                "reviewed_legal_effect_families.import_id",
                "reviewed_legal_effect_families.family_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subject_document_version_id"], ["document_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["object_document_version_id"], ["document_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["basis_document_version_id"], ["document_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["basis_source_provenance_record_id"],
            ["source_provenance_records.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("assertion_id"),
    )
    op.create_index(
        "ix_reviewed_legal_effect_assertions_subject_version",
        "reviewed_legal_effect_assertions",
        ["subject_document_version_id"],
    )
    op.create_index(
        "ix_reviewed_legal_effect_assertions_object_version",
        "reviewed_legal_effect_assertions",
        ["object_document_version_id"],
    )
    op.create_index(
        "ix_reviewed_legal_effect_assertions_family",
        "reviewed_legal_effect_assertions",
        ["import_id", "family_id"],
    )
    op.create_index(
        "ix_reviewed_legal_effect_assertions_relation_kind",
        "reviewed_legal_effect_assertions",
        ["relation_kind"],
    )
    op.create_index(
        "ix_reviewed_legal_effect_assertions_basis_provenance",
        "reviewed_legal_effect_assertions",
        ["basis_source_provenance_record_id"],
    )
    op.create_table(
        "reviewed_legal_effect_events",
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("assertion_id", sa.String(length=128), nullable=False),
        sa.Column("event_kind", sa.String(length=16), nullable=False),
        sa.Column("successor_assertion_id", sa.String(length=128)),
        sa.Column("reason_code", sa.String(length=32), nullable=False),
        sa.Column("reason_note", sa.String(length=500), nullable=False),
        sa.Column("reviewed_by", sa.String(length=128), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_by", sa.String(length=128), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_kind IN ('CORRECTS', 'REVOKES')",
            name="ck_reviewed_legal_effect_events_event_kind",
        ),
        sa.CheckConstraint(
            "reason_code IN ('ENDPOINT_NOT_FOUND', 'VERSION_HASH_MISMATCH', "
            "'PROVENANCE_NOT_FOUND', 'LOCATOR_INVALID', 'DUPLICATE_ASSERTION', "
            "'FAMILY_SCOPE_CONFLICT', 'REVIEW_DISAGREEMENT', "
            "'SUPERSEDED_BY_REVIEW', 'WITHDRAWN_BY_REVIEW')",
            name="ck_reviewed_legal_effect_events_reason_code",
        ),
        sa.CheckConstraint(
            "(event_kind = 'CORRECTS' AND successor_assertion_id IS NOT NULL) OR "
            "(event_kind = 'REVOKES' AND successor_assertion_id IS NULL)",
            name="ck_reviewed_legal_effect_events_successor_shape",
        ),
        sa.CheckConstraint(
            "successor_assertion_id IS NULL OR successor_assertion_id <> assertion_id",
            name="ck_reviewed_legal_effect_events_successor_not_self",
        ),
        sa.CheckConstraint(
            "reviewed_at <= approved_at AND approved_at <= created_at",
            name="ck_reviewed_legal_effect_events_timestamp_order",
        ),
        sa.ForeignKeyConstraint(
            ["assertion_id"], ["reviewed_legal_effect_assertions.assertion_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["successor_assertion_id"],
            ["reviewed_legal_effect_assertions.assertion_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "ix_reviewed_legal_effect_events_assertion",
        "reviewed_legal_effect_events",
        ["assertion_id"],
    )
    op.create_index(
        "ix_reviewed_legal_effect_events_successor",
        "reviewed_legal_effect_events",
        ["successor_assertion_id"],
    )
    op.create_index(
        "ix_reviewed_legal_effect_events_event_kind",
        "reviewed_legal_effect_events",
        ["event_kind"],
    )
    op.execute(
        """
        CREATE FUNCTION reviewed_legal_effect_reject_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'reviewed legal effect registry is append-only';
        END;
        $$
        """
    )
    for table_name in _TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table_name}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table_name} "
            "FOR EACH ROW EXECUTE FUNCTION reviewed_legal_effect_reject_mutation()"
        )


def downgrade() -> None:
    for table_name in reversed(_TABLES):
        op.execute(f"DROP TRIGGER trg_{table_name}_append_only ON {table_name}")
    op.execute("DROP FUNCTION reviewed_legal_effect_reject_mutation()")
    op.drop_table("reviewed_legal_effect_events")
    op.drop_table("reviewed_legal_effect_assertions")
    op.drop_table("reviewed_legal_effect_families")
    op.drop_table("reviewed_legal_effect_imports")
