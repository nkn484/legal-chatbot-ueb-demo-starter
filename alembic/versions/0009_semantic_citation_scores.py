"""Allow auditable lexical and semantic citation component scores.

Revision ID: 0009_semantic_citation_scores
Revises: 0008_lexical_retrieval_repair

Downgrade is conservative: it refuses when a semantic-only citation would lose
its sole score. Remove or transform such rows only in disposable test databases.
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_semantic_citation_scores"
down_revision = "0008_lexical_retrieval_repair"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_citation_records_lexical_score_finite_nonnegative", "citation_records")
    op.alter_column("citation_records", "lexical_score", existing_type=sa.Double(), nullable=True)
    op.add_column("citation_records", sa.Column("semantic_score", sa.Double(), nullable=True))
    op.create_check_constraint(
        "ck_citation_records_lexical_score_finite_nonnegative",
        "citation_records",
        "lexical_score IS NULL OR (lexical_score >= 0 "
        "AND lexical_score <> 'NaN'::double precision "
        "AND lexical_score <> 'Infinity'::double precision "
        "AND lexical_score <> '-Infinity'::double precision)",
    )
    op.create_check_constraint(
        "ck_citation_records_semantic_score_finite_range",
        "citation_records",
        "semantic_score IS NULL OR (semantic_score BETWEEN -1 AND 1 "
        "AND semantic_score <> 'NaN'::double precision "
        "AND semantic_score <> 'Infinity'::double precision "
        "AND semantic_score <> '-Infinity'::double precision)",
    )
    op.create_check_constraint(
        "ck_citation_records_at_least_one_score",
        "citation_records",
        "lexical_score IS NOT NULL OR semantic_score IS NOT NULL",
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM citation_records "
        "WHERE lexical_score IS NULL AND semantic_score IS NOT NULL) THEN "
        "RAISE EXCEPTION 'cannot downgrade semantic-only citation scores'; END IF; END $$"
    )
    op.drop_constraint("ck_citation_records_at_least_one_score", "citation_records")
    op.drop_constraint("ck_citation_records_semantic_score_finite_range", "citation_records")
    op.drop_constraint("ck_citation_records_lexical_score_finite_nonnegative", "citation_records")
    op.drop_column("citation_records", "semantic_score")
    op.alter_column("citation_records", "lexical_score", existing_type=sa.Double(), nullable=False)
    op.create_check_constraint(
        "ck_citation_records_lexical_score_finite_nonnegative",
        "citation_records",
        "lexical_score >= 0 AND lexical_score <> 'NaN'::double precision "
        "AND lexical_score <> 'Infinity'::double precision "
        "AND lexical_score <> '-Infinity'::double precision",
    )
