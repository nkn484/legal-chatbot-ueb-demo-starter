"""Add lexical retrieval evidence and immutable citation persistence.

Revision ID: 0003_retrieval_citation
Revises: 0002_documents_ingestion
Create Date: 2026-08-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0003_retrieval_citation"
down_revision = "0002_documents_ingestion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_chunks",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('pg_catalog.simple', content_text)", persisted=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_document_chunks_search_vector_gin",
        "document_chunks",
        ["search_vector"],
        postgresql_using="gin",
    )

    op.create_table(
        "retrieval_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy", sa.String(length=64), nullable=False),
        sa.Column("strategy_version", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("query_max_chars", sa.Integer(), nullable=False),
        sa.Column("top_k", sa.Integer(), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("citation_count", sa.Integer(), nullable=False),
        sa.Column("evidence_decision", sa.String(length=64), nullable=False),
        sa.Column("evidence_reason", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "scope = 'LATEST_INGESTED'", name="ck_retrieval_runs_scope_latest_ingested"
        ),
        sa.CheckConstraint(
            "query_max_chars BETWEEN 1 AND 4000",
            name="ck_retrieval_runs_query_max_chars_range",
        ),
        sa.CheckConstraint("top_k BETWEEN 1 AND 20", name="ck_retrieval_runs_top_k_range"),
        sa.CheckConstraint(
            "candidate_count >= 0", name="ck_retrieval_runs_candidate_count_nonnegative"
        ),
        sa.CheckConstraint(
            "citation_count >= 0", name="ck_retrieval_runs_citation_count_nonnegative"
        ),
        sa.CheckConstraint(
            "citation_count <= candidate_count",
            name="ck_retrieval_runs_citation_count_within_candidates",
        ),
        sa.CheckConstraint(
            "evidence_decision IN "
            "('EVIDENCE_AVAILABLE', 'NO_RESULTS', 'UNSUPPORTED_TEMPORAL_SCOPE', "
            "'INVALID_EVIDENCE_CHAIN')",
            name="ck_retrieval_runs_evidence_decision",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_retrieval_runs_created_at", "retrieval_runs", ["created_at"])

    op.create_table(
        "citation_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("retrieval_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_provenance_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("lexical_score", sa.Double(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("rank > 0", name="ck_citation_records_rank_positive"),
        sa.CheckConstraint(
            "lexical_score >= 0 "
            "AND lexical_score <> 'NaN'::double precision "
            "AND lexical_score <> 'Infinity'::double precision "
            "AND lexical_score <> '-Infinity'::double precision",
            name="ck_citation_records_lexical_score_finite_nonnegative",
        ),
        sa.ForeignKeyConstraint(["retrieval_run_id"], ["retrieval_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_chunk_id"], ["document_chunks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_provenance_record_id"],
            ["source_provenance_records.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("retrieval_run_id", "rank", name="uq_citation_records_run_rank"),
        sa.UniqueConstraint(
            "retrieval_run_id", "document_chunk_id", name="uq_citation_records_run_chunk"
        ),
    )
    op.create_index(
        "ix_citation_records_retrieval_run_id", "citation_records", ["retrieval_run_id"]
    )
    op.create_index(
        "ix_citation_records_document_chunk_id", "citation_records", ["document_chunk_id"]
    )
    op.create_index(
        "ix_citation_records_source_provenance_record_id",
        "citation_records",
        ["source_provenance_record_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_citation_records_source_provenance_record_id", table_name="citation_records")
    op.drop_index("ix_citation_records_document_chunk_id", table_name="citation_records")
    op.drop_index("ix_citation_records_retrieval_run_id", table_name="citation_records")
    op.drop_table("citation_records")
    op.drop_index("ix_retrieval_runs_created_at", table_name="retrieval_runs")
    op.drop_table("retrieval_runs")
    op.drop_index("ix_document_chunks_search_vector_gin", table_name="document_chunks")
    op.drop_column("document_chunks", "search_vector")
