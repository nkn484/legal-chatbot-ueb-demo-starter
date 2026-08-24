"""SQLAlchemy persistence schema for M08 channel delivery state.

FAILED bindings retain a normalized safe error code and may retain no
conversation or a previously associated conversation.  They never retain an
active lease or activation timestamp.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func, text

from legal_chatbot.db.base import Base


class ChannelConversationBinding(Base):
    """A lease-backed, privacy-preserving channel identity binding."""

    __tablename__ = "channel_conversation_bindings"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_channel_conversation_bindings"),
        UniqueConstraint(
            "channel_kind",
            "identity_hmac",
            name="uq_channel_conversation_bindings_channel_identity_hmac",
        ),
        CheckConstraint(
            "channel_kind = 'ZALO_OFFICIAL_BOT'",
            name="ck_channel_conversation_bindings_channel_kind",
        ),
        CheckConstraint(
            "identity_hmac ~ '^[0-9a-f]{64}$'",
            name="ck_channel_conversation_bindings_identity_hmac",
        ),
        CheckConstraint(
            "safe_error_code IS NULL OR safe_error_code ~ '^[A-Z][A-Z0-9_]{0,63}$'",
            name="ck_channel_conversation_bindings_safe_error_code",
        ),
        CheckConstraint(
            "status IN ('BINDING', 'ACTIVE', 'FAILED')",
            name="ck_channel_conversation_bindings_status",
        ),
        CheckConstraint(
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
        Index("ix_channel_conversation_bindings_lease_expires_at", "lease_expires_at"),
        Index(
            "uq_channel_conversation_bindings_active_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    channel_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    identity_hmac: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "conversations.id",
            name="fk_channel_conversation_bindings_conversation_id_conversations",
            ondelete="CASCADE",
        )
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    safe_error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    outbound_deliveries: Mapped[list[ChannelOutboundDelivery]] = relationship(
        back_populates="binding", cascade="all, delete-orphan", passive_deletes=True
    )


class ChannelOutboundDelivery(Base):
    """One bounded outbound delivery attempt for a channel exchange."""

    __tablename__ = "channel_outbound_deliveries"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_channel_outbound_deliveries"),
        UniqueConstraint(
            "channel_kind",
            "binding_id",
            "exchange_id",
            name="uq_channel_outbound_deliveries_channel_binding_exchange",
        ),
        UniqueConstraint(
            "channel_kind",
            "delivery_hmac",
            name="uq_channel_outbound_deliveries_channel_delivery_hmac",
        ),
        CheckConstraint(
            "channel_kind = 'ZALO_OFFICIAL_BOT'",
            name="ck_channel_outbound_deliveries_channel_kind",
        ),
        CheckConstraint(
            "delivery_hmac ~ '^[0-9a-f]{64}$'",
            name="ck_channel_outbound_deliveries_delivery_hmac",
        ),
        CheckConstraint(
            "safe_error_code IS NULL OR safe_error_code ~ '^[A-Z][A-Z0-9_]{0,63}$'",
            name="ck_channel_outbound_deliveries_safe_error_code",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'SENDING', 'SENT', 'FAILED', 'UNKNOWN', 'ABANDONED')",
            name="ck_channel_outbound_deliveries_status",
        ),
        CheckConstraint(
            "attempt_count BETWEEN 0 AND 1",
            name="ck_channel_outbound_deliveries_attempt_count_range",
        ),
        CheckConstraint(
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
        Index("ix_channel_outbound_deliveries_binding_created_at", "binding_id", "created_at"),
        Index("ix_channel_outbound_deliveries_status_created_at", "status", "created_at"),
        Index(
            "uq_channel_outbound_deliveries_sending_binding",
            "binding_id",
            unique=True,
            postgresql_where=text("status = 'SENDING'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    channel_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    binding_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "channel_conversation_bindings.id",
            name="fk_channel_outbound_deliveries_binding_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    exchange_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "conversation_exchanges.id",
            name="fk_channel_outbound_deliveries_exchange_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    delivery_hmac: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    safe_error_code: Mapped[str | None] = mapped_column(String(64))
    attempt_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    sending_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    binding: Mapped[ChannelConversationBinding] = relationship(back_populates="outbound_deliveries")
