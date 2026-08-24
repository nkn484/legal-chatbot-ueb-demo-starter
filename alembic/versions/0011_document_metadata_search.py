"""Add derived canonical document keys and generated title full-text search.

Revision ID: 0011_document_metadata_search
Revises: 0010_reranker_scores
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011_document_metadata_search"
down_revision = "0010_reranker_scores"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_versions",
        sa.Column("document_number_normalized", sa.String(length=256), nullable=True),
    )
    op.create_index(
        "ix_document_versions_document_number_normalized",
        "document_versions",
        ["document_number_normalized"],
        unique=False,
    )
    op.add_column(
        "document_versions",
        sa.Column(
            "title_search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('pg_catalog.simple', coalesce(title, ''))", persisted=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_document_versions_title_search_vector_gin",
        "document_versions",
        ["title_search_vector"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_document_versions_title_search_vector_gin", table_name="document_versions")
    op.drop_column("document_versions", "title_search_vector")
    op.drop_index("ix_document_versions_document_number_normalized", table_name="document_versions")
    op.drop_column("document_versions", "document_number_normalized")
