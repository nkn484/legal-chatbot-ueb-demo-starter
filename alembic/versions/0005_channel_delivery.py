"""Add M08 channel binding and outbound delivery persistence.

Revision ID: 0005_channel_delivery
Revises: 0004_conversation_state
Create Date: 2026-08-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0005_channel_delivery"
down_revision = "0004_conversation_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_conversation_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_kind", sa.String(length=32), nullable=False),
        sa.Column("identity_hmac", sa.CHAR(length=64), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True)),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("safe_error_code", sa.String(length=64)),
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
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "channel_kind = 'ZALO_OFFICIAL_BOT'",
            name="ck_channel_conversation_bindings_channel_kind",
        ),
        sa.CheckConstraint(
            "identity_hmac ~ '^[0-9a-f]{64}$'",
            name="ck_channel_conversation_bindings_identity_hmac",
        ),
        sa.CheckConstraint(
            "safe_error_code IS NULL OR safe_error_code ~ '^[A-Z][A-Z0-9_]{0,63}$'",
            name="ck_channel_conversation_bindings_safe_error_code",
        ),
        sa.CheckConstraint(
            "status IN ('BINDING', 'ACTIVE', 'FAILED')",
            name="ck_channel_conversation_bindings_status",
        ),
        sa.CheckConstraint(
            "(status = 'BINDING' "
            "AND conversation_id IS NULL "
            "AND lease_expires_at IS NOT NULL "
            "AND safe_error_code IS NULL "
            "AND activated_at IS NULL) "
            "OR (status = 'ACTIVE' "
            "AND conversation_id IS NOT NULL "
            "AND lease_expires_at IS NULL "
            "AND safe_error_code IS NULL "
            "AND activated_at IS NOT NULL) "
            "OR (status = 'FAILED' "
            "AND lease_expires_at IS NULL "
            "AND safe_error_code IS NOT NULL "
            "AND activated_at IS NULL)",
            name="ck_channel_conversation_bindings_status_shape",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_channel_conversation_bindings_conversation_id_conversations",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_channel_conversation_bindings"),
        sa.UniqueConstraint(
            "channel_kind",
            "identity_hmac",
            name="uq_channel_conversation_bindings_channel_identity_hmac",
        ),
    )
    op.create_index(
        "ix_channel_conversation_bindings_lease_expires_at",
        "channel_conversation_bindings",
        ["lease_expires_at"],
    )
    op.create_index(
        "uq_channel_conversation_bindings_active_conversation",
        "channel_conversation_bindings",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )

    op.create_table(
        "channel_outbound_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_kind", sa.String(length=32), nullable=False),
        sa.Column("binding_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exchange_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delivery_hmac", sa.CHAR(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("safe_error_code", sa.String(length=64)),
        sa.Column("attempt_count", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sending_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "channel_kind = 'ZALO_OFFICIAL_BOT'",
            name="ck_channel_outbound_deliveries_channel_kind",
        ),
        sa.CheckConstraint(
            "delivery_hmac ~ '^[0-9a-f]{64}$'",
            name="ck_channel_outbound_deliveries_delivery_hmac",
        ),
        sa.CheckConstraint(
            "safe_error_code IS NULL OR safe_error_code ~ '^[A-Z][A-Z0-9_]{0,63}$'",
            name="ck_channel_outbound_deliveries_safe_error_code",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'SENDING', 'SENT', 'FAILED', 'UNKNOWN', 'ABANDONED')",
            name="ck_channel_outbound_deliveries_status",
        ),
        sa.CheckConstraint(
            "attempt_count BETWEEN 0 AND 1",
            name="ck_channel_outbound_deliveries_attempt_count_range",
        ),
        sa.CheckConstraint(
            "(status = 'PENDING' "
            "AND attempt_count = 0 "
            "AND sending_at IS NULL "
            "AND completed_at IS NULL "
            "AND safe_error_code IS NULL) "
            "OR (status = 'SENDING' "
            "AND attempt_count = 1 "
            "AND sending_at IS NOT NULL "
            "AND completed_at IS NULL "
            "AND safe_error_code IS NULL) "
            "OR (status = 'SENT' "
            "AND attempt_count = 1 "
            "AND sending_at IS NOT NULL "
            "AND completed_at IS NOT NULL "
            "AND safe_error_code IS NULL) "
            "OR (status IN ('FAILED', 'UNKNOWN') "
            "AND attempt_count = 1 "
            "AND sending_at IS NOT NULL "
            "AND completed_at IS NOT NULL "
            "AND safe_error_code IS NOT NULL) "
            "OR (status = 'ABANDONED' "
            "AND attempt_count IN (0, 1) "
            "AND completed_at IS NOT NULL "
            "AND safe_error_code IS NOT NULL "
            "AND ((attempt_count = 0 AND sending_at IS NULL) "
            "OR (attempt_count = 1 AND sending_at IS NOT NULL)))",
            name="ck_channel_outbound_deliveries_status_shape",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"],
            ["channel_conversation_bindings.id"],
            name="fk_channel_outbound_deliveries_binding_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["exchange_id"],
            ["conversation_exchanges.id"],
            name="fk_channel_outbound_deliveries_exchange_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_channel_outbound_deliveries"),
        sa.UniqueConstraint(
            "channel_kind",
            "binding_id",
            "exchange_id",
            name="uq_channel_outbound_deliveries_channel_binding_exchange",
        ),
        sa.UniqueConstraint(
            "channel_kind",
            "delivery_hmac",
            name="uq_channel_outbound_deliveries_channel_delivery_hmac",
        ),
    )
    op.create_index(
        "ix_channel_outbound_deliveries_binding_created_at",
        "channel_outbound_deliveries",
        ["binding_id", "created_at"],
    )
    op.create_index(
        "ix_channel_outbound_deliveries_status_created_at",
        "channel_outbound_deliveries",
        ["status", "created_at"],
    )
    op.create_index(
        "uq_channel_outbound_deliveries_sending_binding",
        "channel_outbound_deliveries",
        ["binding_id"],
        unique=True,
        postgresql_where=sa.text("status = 'SENDING'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_channel_outbound_deliveries_sending_binding", table_name="channel_outbound_deliveries"
    )
    op.drop_index(
        "ix_channel_outbound_deliveries_status_created_at", table_name="channel_outbound_deliveries"
    )
    op.drop_index(
        "ix_channel_outbound_deliveries_binding_created_at",
        table_name="channel_outbound_deliveries",
    )
    op.drop_table("channel_outbound_deliveries")
    op.drop_index(
        "uq_channel_conversation_bindings_active_conversation",
        table_name="channel_conversation_bindings",
    )
    op.drop_index(
        "ix_channel_conversation_bindings_lease_expires_at",
        table_name="channel_conversation_bindings",
    )
    op.drop_table("channel_conversation_bindings")
