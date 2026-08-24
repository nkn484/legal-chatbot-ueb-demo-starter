"""Add an optional auditable reranker component score to citations.

Revision ID: 0010_reranker_scores
Revises: 0009_semantic_citation_scores
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_reranker_scores"
down_revision = "0009_semantic_citation_scores"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("citation_records", sa.Column("reranker_score", sa.Double(), nullable=True))
    op.create_check_constraint(
        "ck_citation_records_reranker_score_finite",
        "citation_records",
        "reranker_score IS NULL OR (reranker_score <> 'NaN'::double precision "
        "AND reranker_score <> 'Infinity'::double precision "
        "AND reranker_score <> '-Infinity'::double precision)",
    )


def downgrade() -> None:
    """Drop supplemental data safely; lexical/semantic score history remains intact."""

    op.drop_constraint("ck_citation_records_reranker_score_finite", "citation_records")
    op.drop_column("citation_records", "reranker_score")
