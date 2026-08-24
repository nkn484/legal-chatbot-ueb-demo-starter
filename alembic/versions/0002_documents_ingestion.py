"""Create source document, version, chunk, and embedding persistence tables.

Revision ID: 0002_documents_ingestion
Revises: 0001_enable_pgvector
Create Date: 2026-08-19
"""

from alembic import op
import pgvector.sqlalchemy
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0002_documents_ingestion"
down_revision = "0001_enable_pgvector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "legal_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "external_id", name="uq_legal_documents_source_external"),
    )
    op.create_index("ix_legal_documents_source_id", "legal_documents", ["source_id"])

    op.create_table(
        "document_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("document_number", sa.String(length=256)),
        sa.Column("title", sa.String(length=4096)),
        sa.Column("document_type", sa.String(length=512)),
        sa.Column("issuing_authority", sa.String(length=1024)),
        sa.Column("issue_date", sa.DateTime(timezone=True)),
        sa.Column("effective_date", sa.DateTime(timezone=True)),
        sa.Column("source_updated_at", sa.DateTime(timezone=True)),
        sa.Column("legal_status", sa.String(length=256)),
        sa.Column("canonical_url", sa.String(length=2048)),
        sa.Column("raw_html", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("snapshot_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("source_content_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("normalized_text_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("normalizer_version", sa.String(length=64), nullable=False),
        sa.Column("normalized_block_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("version_number > 0", name="ck_document_versions_version_number_positive"),
        sa.CheckConstraint(
            "normalized_block_count >= 1", name="ck_document_versions_normalized_block_count_positive"
        ),
        sa.CheckConstraint(
            "snapshot_sha256 ~ '^[0-9a-f]{64}$'", name="ck_document_versions_snapshot_sha256"
        ),
        sa.CheckConstraint(
            "source_content_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_document_versions_source_content_sha256",
        ),
        sa.CheckConstraint(
            "normalized_text_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_document_versions_normalized_text_sha256",
        ),
        sa.ForeignKeyConstraint(["document_id"], ["legal_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "snapshot_sha256", name="uq_document_versions_document_snapshot"),
        sa.UniqueConstraint(
            "document_id", "version_number", name="uq_document_versions_document_version_number"
        ),
    )
    op.create_index("ix_document_versions_document_id", "document_versions", ["document_id"])
    op.create_index("ix_document_versions_source_updated_at", "document_versions", ["source_updated_at"])

    op.create_table(
        "source_provenance_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provenance_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=32), nullable=False),
        sa.Column("transport", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=128), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("canonical_url", sa.String(length=2048)),
        sa.Column("tls_verified", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_source_provenance_records_version_id", "source_provenance_records", ["document_version_id"]
    )
    op.create_index(
        "ix_source_provenance_records_source_retrieved_at",
        "source_provenance_records",
        ["source_id", "retrieved_at"],
    )

    op.create_table(
        "document_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("start_char", sa.Integer(), nullable=False),
        sa.Column("end_char", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("chunker_version", sa.String(length=64), nullable=False),
        sa.Column("locator", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("end_char > start_char", name="ck_document_chunks_chars_ordered"),
        sa.CheckConstraint("ordinal >= 0", name="ck_document_chunks_ordinal_nonnegative"),
        sa.CheckConstraint("start_char >= 0", name="ck_document_chunks_start_char_nonnegative"),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_document_chunks_content_sha256"
        ),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_version_id", "ordinal", name="uq_document_chunks_version_ordinal"),
    )
    op.create_index("ix_document_chunks_document_version_id", "document_chunks", ["document_version_id"])

    op.create_table(
        "chunk_embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(dim=384), nullable=False),
        sa.Column("embedding_model_id", sa.String(length=256), nullable=False),
        sa.Column("embedding_kind", sa.String(length=64), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("embedding_input_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("dimension = 384", name="ck_chunk_embeddings_dimension_384"),
        sa.CheckConstraint(
            "embedding_input_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_chunk_embeddings_embedding_input_sha256",
        ),
        sa.ForeignKeyConstraint(["document_chunk_id"], ["document_chunks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_chunk_id", "embedding_model_id", name="uq_chunk_embeddings_chunk_model_id"
        ),
    )
    op.create_index("ix_chunk_embeddings_document_chunk_id", "chunk_embeddings", ["document_chunk_id"])
    op.create_index(
        "ix_chunk_embeddings_embedding_hnsw_cosine",
        "chunk_embeddings",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_chunk_embeddings_embedding_hnsw_cosine", table_name="chunk_embeddings")
    op.drop_index("ix_chunk_embeddings_document_chunk_id", table_name="chunk_embeddings")
    op.drop_table("chunk_embeddings")
    op.drop_index("ix_document_chunks_document_version_id", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index(
        "ix_source_provenance_records_source_retrieved_at", table_name="source_provenance_records"
    )
    op.drop_index("ix_source_provenance_records_version_id", table_name="source_provenance_records")
    op.drop_table("source_provenance_records")
    op.drop_index("ix_document_versions_source_updated_at", table_name="document_versions")
    op.drop_index("ix_document_versions_document_id", table_name="document_versions")
    op.drop_table("document_versions")
    op.drop_index("ix_legal_documents_source_id", table_name="legal_documents")
    op.drop_table("legal_documents")
