"""Add bounded conversation state and idempotent exchange persistence.

Revision ID: 0004_conversation_state
Revises: 0003_retrieval_citation
Create Date: 2026-08-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0004_conversation_state"
down_revision = "0003_retrieval_citation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state_version", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("rolling_summary", sa.String(length=1500)),
        sa.Column("active_topic", sa.String(length=256)),
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
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("state_version >= 0", name="ck_conversations_state_version_nonnegative"),
        sa.CheckConstraint(
            "expires_at > created_at", name="ck_conversations_expires_after_created"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
    )
    op.create_index("ix_conversations_expires_at", "conversations", ["expires_at"])
    op.create_index("ix_conversations_updated_at", "conversations", ["updated_at"])

    op.create_table(
        "conversation_exchanges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delivery_key_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("user_text", sa.Text(), nullable=False),
        sa.Column("assistant_text", sa.Text()),
        sa.Column("chat_outcome", sa.String(length=16)),
        sa.Column("chat_reason", sa.String(length=64)),
        sa.Column("retrieval_run_id", postgresql.UUID(as_uuid=True)),
        sa.Column("provider", sa.String(length=128)),
        sa.Column("model", sa.String(length=128)),
        sa.Column("request_id", sa.String(length=128)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "delivery_key_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_conversation_exchanges_delivery_key_sha256",
        ),
        sa.CheckConstraint("ordinal > 0", name="ck_conversation_exchanges_ordinal_positive"),
        sa.CheckConstraint(
            "status IN ('PROCESSING', 'COMPLETED', 'FAILED', 'ABANDONED')",
            name="ck_conversation_exchanges_status",
        ),
        sa.CheckConstraint(
            "char_length(user_text) BETWEEN 1 AND 4000",
            name="ck_conversation_exchanges_user_text_length",
        ),
        sa.CheckConstraint(
            "assistant_text IS NULL OR char_length(assistant_text) BETWEEN 1 AND 4000",
            name="ck_conversation_exchanges_assistant_text_length",
        ),
        sa.CheckConstraint(
            "chat_outcome IS NULL OR chat_outcome IN ('ANSWER', 'CLARIFICATION', 'REFUSAL')",
            name="ck_conversation_exchanges_chat_outcome",
        ),
        sa.CheckConstraint(
            "(status = 'PROCESSING' "
            "AND lease_expires_at IS NOT NULL "
            "AND completed_at IS NULL "
            "AND assistant_text IS NULL "
            "AND chat_outcome IS NULL "
            "AND chat_reason IS NULL "
            "AND retrieval_run_id IS NULL "
            "AND provider IS NULL "
            "AND model IS NULL "
            "AND request_id IS NULL) "
            "OR (status = 'COMPLETED' "
            "AND lease_expires_at IS NULL "
            "AND completed_at IS NOT NULL "
            "AND assistant_text IS NOT NULL "
            "AND chat_outcome IS NOT NULL "
            "AND chat_reason IS NOT NULL) "
            "OR (status IN ('FAILED', 'ABANDONED') "
            "AND lease_expires_at IS NULL "
            "AND completed_at IS NULL "
            "AND assistant_text IS NULL "
            "AND chat_outcome IS NULL "
            "AND retrieval_run_id IS NULL "
            "AND provider IS NULL "
            "AND model IS NULL "
            "AND request_id IS NULL)",
            name="ck_conversation_exchanges_status_shape",
        ),
        sa.CheckConstraint(
            "status <> 'COMPLETED' OR "
            "(chat_outcome = 'ANSWER' "
            "AND chat_reason = 'ANSWER_GROUNDED' "
            "AND retrieval_run_id IS NOT NULL "
            "AND provider IS NOT NULL "
            "AND model IS NOT NULL) "
            "OR (chat_outcome = 'CLARIFICATION' "
            "AND chat_reason = 'NO_RESULTS' "
            "AND retrieval_run_id IS NOT NULL "
            "AND provider IS NULL "
            "AND model IS NULL "
            "AND request_id IS NULL) "
            "OR (chat_outcome = 'REFUSAL' "
            "AND chat_reason IN ('UNSUPPORTED_TEMPORAL_SCOPE', 'INVALID_EVIDENCE_CHAIN', "
            "'RETRIEVAL_FAILURE', 'GROUNDING_FAILURE', 'PROVIDER_FAILURE', "
            "'INVALID_PROVIDER_OUTPUT', 'CITATION_REVALIDATION_FAILURE') "
            "AND provider IS NULL "
            "AND model IS NULL "
            "AND request_id IS NULL "
            "AND ((chat_reason = 'RETRIEVAL_FAILURE' AND retrieval_run_id IS NULL) "
            "OR (chat_reason IN ('UNSUPPORTED_TEMPORAL_SCOPE', 'INVALID_EVIDENCE_CHAIN', "
            "'GROUNDING_FAILURE', 'PROVIDER_FAILURE', 'INVALID_PROVIDER_OUTPUT', "
            "'CITATION_REVALIDATION_FAILURE') AND retrieval_run_id IS NOT NULL)))",
            name="ck_conversation_exchanges_completed_result_shape",
        ),
        sa.CheckConstraint(
            "status NOT IN ('FAILED', 'ABANDONED') "
            "OR chat_reason IS NULL "
            "OR chat_reason IN ('LEASE_EXPIRED', 'PROCESSING_FAILED', 'ABANDONED_BY_SYSTEM')",
            name="ck_conversation_exchanges_failure_reason",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_conversation_exchanges_conversation_id_conversations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["retrieval_run_id"],
            ["retrieval_runs.id"],
            name="fk_conversation_exchanges_retrieval_run_id_retrieval_runs",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversation_exchanges"),
        sa.UniqueConstraint(
            "conversation_id",
            "delivery_key_sha256",
            name="uq_conversation_exchanges_conversation_delivery_key_sha256",
        ),
        sa.UniqueConstraint(
            "conversation_id", "ordinal", name="uq_conversation_exchanges_conversation_ordinal"
        ),
    )
    op.create_index(
        "ix_conversation_exchanges_conversation_created_at",
        "conversation_exchanges",
        ["conversation_id", "created_at"],
    )
    op.create_index(
        "ix_conversation_exchanges_lease_expires_at", "conversation_exchanges", ["lease_expires_at"]
    )
    op.create_index(
        "uq_conversation_exchanges_processing_conversation",
        "conversation_exchanges",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PROCESSING'"),
    )

    op.create_table(
        "conversation_exchange_references",
        sa.Column("exchange_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('CITATION', 'DOCUMENT')", name="ck_conversation_exchange_references_kind"
        ),
        sa.CheckConstraint(
            "ordinal BETWEEN 0 AND 5", name="ck_conversation_exchange_references_ordinal_range"
        ),
        sa.ForeignKeyConstraint(
            ["exchange_id"],
            ["conversation_exchanges.id"],
            name="fk_conv_exchange_refs_exchange_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "exchange_id", "kind", "ordinal", name="pk_conversation_exchange_references"
        ),
        sa.UniqueConstraint(
            "exchange_id",
            "kind",
            "reference_id",
            name="uq_conversation_exchange_references_exchange_kind_reference",
        ),
    )
    op.create_index(
        "ix_conversation_exchange_references_reference_id",
        "conversation_exchange_references",
        ["reference_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_exchange_references_reference_id",
        table_name="conversation_exchange_references",
    )
    op.drop_table("conversation_exchange_references")
    op.drop_index(
        "uq_conversation_exchanges_processing_conversation", table_name="conversation_exchanges"
    )
    op.drop_index("ix_conversation_exchanges_lease_expires_at", table_name="conversation_exchanges")
    op.drop_index(
        "ix_conversation_exchanges_conversation_created_at", table_name="conversation_exchanges"
    )
    op.drop_table("conversation_exchanges")
    op.drop_index("ix_conversations_updated_at", table_name="conversations")
    op.drop_index("ix_conversations_expires_at", table_name="conversations")
    op.drop_table("conversations")
