"""Enable the pgvector extension.

Revision ID: 0001_enable_pgvector
Revises:
Create Date: 2026-08-19
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "0001_enable_pgvector"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")
