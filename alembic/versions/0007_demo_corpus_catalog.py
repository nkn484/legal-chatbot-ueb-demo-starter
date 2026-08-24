"""Add catalog and run state for the approved manual demo corpus.

Revision ID: 0007_demo_corpus_catalog
Revises: 0006_tls_trust_provenance
Create Date: 2026-08-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_demo_corpus_catalog"
down_revision = "0006_tls_trust_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "corpus_ingestion_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_id", sa.String(length=128), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'COMPLETED', 'COMPLETED_WITH_FAILURES', 'FAILED')",
            name="ck_corpus_ingestion_runs_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_corpus_ingestion_runs_dataset_started",
        "corpus_ingestion_runs",
        ["dataset_id", "started_at"],
    )
    op.create_table(
        "corpus_catalog_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_id", sa.String(length=128), nullable=False),
        sa.Column("source_id", sa.String(length=32), nullable=False),
        sa.Column("workbook_name", sa.String(length=512), nullable=False),
        sa.Column("sheet_name", sa.String(length=128), nullable=False),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=256), nullable=False),
        sa.Column("document_number", sa.String(length=256)),
        sa.Column("title", sa.String(length=4096)),
        sa.Column("document_type", sa.String(length=512)),
        sa.Column("issuing_authority", sa.String(length=1024)),
        sa.Column("issue_date", sa.DateTime(timezone=True)),
        sa.Column("effective_date", sa.DateTime(timezone=True)),
        sa.Column("legal_status", sa.String(length=256)),
        sa.Column("file_label", sa.String(length=2048)),
        sa.Column("file_url", sa.String(length=2048)),
        sa.Column("file_kind", sa.String(length=32), nullable=False),
        sa.Column("record_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("processing_status", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=128)),
        sa.Column("file_sha256", sa.CHAR(length=64)),
        sa.Column("legal_document_id", postgresql.UUID(as_uuid=True)),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_id IN ('VBQPPL', 'VNU', 'UEB')", name="ck_corpus_catalog_entries_source_id"
        ),
        sa.CheckConstraint(
            "file_kind IN ('DIRECT_FILE', 'FOLDER', 'MISSING', 'UNRESOLVED')",
            name="ck_corpus_catalog_entries_file_kind",
        ),
        sa.CheckConstraint(
            "processing_status IN ('DISCOVERED', 'FILE_PENDING', 'FILE_DOWNLOADED', "
            "'EXTRACTED', 'OCR_REQUIRED', 'CHUNKED', 'INDEXED', 'QUARANTINED', 'FAILED')",
            name="ck_corpus_catalog_entries_processing_status",
        ),
        sa.CheckConstraint("source_row >= 2", name="ck_corpus_catalog_entries_source_row_positive"),
        sa.CheckConstraint(
            "record_sha256 ~ '^[0-9a-f]{64}$'", name="ck_corpus_catalog_entries_record_sha256"
        ),
        sa.CheckConstraint(
            "file_sha256 IS NULL OR file_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_corpus_catalog_entries_file_sha256",
        ),
        sa.ForeignKeyConstraint(["legal_document_id"], ["legal_documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dataset_id",
            "source_id",
            "workbook_name",
            "sheet_name",
            "source_row",
            name="uq_corpus_catalog_entries_source_row",
        ),
    )
    op.create_index(
        "ix_corpus_catalog_entries_dataset_source",
        "corpus_catalog_entries",
        ["dataset_id", "source_id"],
    )
    op.create_index(
        "ix_corpus_catalog_entries_status", "corpus_catalog_entries", ["processing_status"]
    )


def downgrade() -> None:
    op.drop_index("ix_corpus_catalog_entries_status", table_name="corpus_catalog_entries")
    op.drop_index("ix_corpus_catalog_entries_dataset_source", table_name="corpus_catalog_entries")
    op.drop_table("corpus_catalog_entries")
    op.drop_index("ix_corpus_ingestion_runs_dataset_started", table_name="corpus_ingestion_runs")
    op.drop_table("corpus_ingestion_runs")
