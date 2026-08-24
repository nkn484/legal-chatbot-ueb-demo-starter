"""SQLAlchemy persistence schema for bounded conversation state."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func, text

from legal_chatbot.db.base import Base


class Conversation(Base):
    """Durable bounded state for one user conversation."""

    __tablename__ = "conversations"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_conversations"),
        CheckConstraint("state_version >= 0", name="ck_conversations_state_version_nonnegative"),
        CheckConstraint("expires_at > created_at", name="ck_conversations_expires_after_created"),
        Index("ix_conversations_expires_at", "expires_at"),
        Index("ix_conversations_updated_at", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    rolling_summary: Mapped[str | None] = mapped_column(String(1500))
    active_topic: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    exchanges: Mapped[list[ConversationExchange]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", passive_deletes=True
    )


class ConversationExchange(Base):
    """One idempotent user delivery and its bounded processing outcome.

    FAILED and ABANDONED exchanges may retain only a bounded normalized
    conversation failure code; provider and response fields remain absent.
    """

    __tablename__ = "conversation_exchanges"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_conversation_exchanges"),
        UniqueConstraint(
            "conversation_id",
            "delivery_key_sha256",
            name="uq_conversation_exchanges_conversation_delivery_key_sha256",
        ),
        UniqueConstraint(
            "conversation_id", "ordinal", name="uq_conversation_exchanges_conversation_ordinal"
        ),
        CheckConstraint(
            "delivery_key_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_conversation_exchanges_delivery_key_sha256",
        ),
        CheckConstraint("ordinal > 0", name="ck_conversation_exchanges_ordinal_positive"),
        CheckConstraint(
            "status IN ('PROCESSING', 'COMPLETED', 'FAILED', 'ABANDONED')",
            name="ck_conversation_exchanges_status",
        ),
        CheckConstraint(
            "char_length(user_text) BETWEEN 1 AND 4000",
            name="ck_conversation_exchanges_user_text_length",
        ),
        CheckConstraint(
            "assistant_text IS NULL OR char_length(assistant_text) BETWEEN 1 AND 4000",
            name="ck_conversation_exchanges_assistant_text_length",
        ),
        CheckConstraint(
            "chat_outcome IS NULL OR chat_outcome IN ('ANSWER', 'CLARIFICATION', 'REFUSAL')",
            name="ck_conversation_exchanges_chat_outcome",
        ),
        CheckConstraint(
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
        CheckConstraint(
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
        CheckConstraint(
            "status NOT IN ('FAILED', 'ABANDONED') "
            "OR chat_reason IS NULL "
            "OR chat_reason IN ('LEASE_EXPIRED', 'PROCESSING_FAILED', 'ABANDONED_BY_SYSTEM')",
            name="ck_conversation_exchanges_failure_reason",
        ),
        Index("ix_conversation_exchanges_conversation_created_at", "conversation_id", "created_at"),
        Index("ix_conversation_exchanges_lease_expires_at", "lease_expires_at"),
        Index(
            "uq_conversation_exchanges_processing_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=text("status = 'PROCESSING'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "conversations.id",
            name="fk_conversation_exchanges_conversation_id_conversations",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    delivery_key_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_text: Mapped[str] = mapped_column(Text, nullable=False)
    assistant_text: Mapped[str | None] = mapped_column(Text)
    chat_outcome: Mapped[str | None] = mapped_column(String(16))
    chat_reason: Mapped[str | None] = mapped_column(String(64))
    retrieval_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "retrieval_runs.id",
            name="fk_conversation_exchanges_retrieval_run_id_retrieval_runs",
            ondelete="RESTRICT",
        )
    )
    provider: Mapped[str | None] = mapped_column(String(128))
    model: Mapped[str | None] = mapped_column(String(128))
    request_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    conversation: Mapped[Conversation] = relationship(back_populates="exchanges")
    references: Mapped[list[ConversationExchangeReference]] = relationship(
        back_populates="exchange", cascade="all, delete-orphan", passive_deletes=True
    )


class ConversationExchangeReference(Base):
    """A bounded citation or document reference attached to an exchange."""

    __tablename__ = "conversation_exchange_references"
    __table_args__ = (
        PrimaryKeyConstraint(
            "exchange_id", "kind", "ordinal", name="pk_conversation_exchange_references"
        ),
        UniqueConstraint(
            "exchange_id",
            "kind",
            "reference_id",
            name="uq_conversation_exchange_references_exchange_kind_reference",
        ),
        CheckConstraint(
            "kind IN ('CITATION', 'DOCUMENT')", name="ck_conversation_exchange_references_kind"
        ),
        CheckConstraint(
            "ordinal BETWEEN 0 AND 5", name="ck_conversation_exchange_references_ordinal_range"
        ),
        Index("ix_conversation_exchange_references_reference_id", "reference_id"),
    )

    exchange_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "conversation_exchanges.id",
            name="fk_conv_exchange_refs_exchange_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    reference_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    exchange: Mapped[ConversationExchange] = relationship(back_populates="references")
