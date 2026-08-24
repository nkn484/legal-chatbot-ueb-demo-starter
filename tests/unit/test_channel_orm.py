"""Metadata-only checks for M08 channel delivery persistence."""

from pathlib import Path

from sqlalchemy import CHAR, CheckConstraint, PrimaryKeyConstraint, SmallInteger, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from legal_chatbot.channels.orm import ChannelConversationBinding, ChannelOutboundDelivery
from legal_chatbot.conversation.orm import Conversation, ConversationExchange
from legal_chatbot.db.base import Base


def _checks(table) -> dict[str, str]:
    return {
        constraint.name: constraint.sqltext.text
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }


def test_channel_tables_are_registered_without_forbidden_persistence_columns() -> None:
    assert {
        "channel_conversation_bindings",
        "channel_outbound_deliveries",
    } <= set(Base.metadata.tables)

    forbidden_fragments = {
        "text",
        "raw",
        "citation",
        "session",
        "provider",
        "retrieval",
        "document",
    }
    for table in (ChannelConversationBinding.__table__, ChannelOutboundDelivery.__table__):
        assert not {
            column_name
            for column_name in table.columns.keys()
            if any(fragment in column_name for fragment in forbidden_fragments)
        }


def test_binding_metadata_declares_normalized_identity_and_lifecycle_shape() -> None:
    binding = ChannelConversationBinding.__table__

    assert set(binding.columns.keys()) == {
        "id",
        "channel_kind",
        "identity_hmac",
        "conversation_id",
        "status",
        "lease_expires_at",
        "safe_error_code",
        "created_at",
        "updated_at",
        "activated_at",
    }
    assert isinstance(binding.c.id.type, UUID)
    assert binding.c.channel_kind.type.length == 32
    assert isinstance(binding.c.identity_hmac.type, CHAR)
    assert binding.c.identity_hmac.type.length == 64
    assert binding.c.status.type.length == 16
    assert binding.c.safe_error_code.type.length == 64
    assert binding.c.conversation_id.nullable is True
    assert any(
        isinstance(constraint, PrimaryKeyConstraint)
        and tuple(constraint.columns.keys()) == ("id",)
        and constraint.name == "pk_channel_conversation_bindings"
        for constraint in binding.constraints
    )
    assert {
        (constraint.name, tuple(constraint.columns.keys()))
        for constraint in binding.constraints
        if isinstance(constraint, UniqueConstraint)
    } == {
        (
            "uq_channel_conversation_bindings_channel_identity_hmac",
            ("channel_kind", "identity_hmac"),
        )
    }
    assert _checks(binding) == {
        "ck_channel_conversation_bindings_channel_kind": "channel_kind = 'ZALO_OFFICIAL_BOT'",
        "ck_channel_conversation_bindings_identity_hmac": "identity_hmac ~ '^[0-9a-f]{64}$'",
        "ck_channel_conversation_bindings_safe_error_code": (
            "safe_error_code IS NULL OR safe_error_code ~ '^[A-Z][A-Z0-9_]{0,63}$'"
        ),
        "ck_channel_conversation_bindings_status": "status IN ('BINDING', 'ACTIVE', 'FAILED')",
        "ck_channel_conversation_bindings_status_shape": (
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
            "AND activated_at IS NULL)"
        ),
    }
    assert {
        foreign_key.parent.name: (foreign_key.target_fullname, foreign_key.ondelete)
        for foreign_key in binding.foreign_keys
    } == {"conversation_id": ("conversations.id", "CASCADE")}
    assert {index.name for index in binding.indexes} == {
        "ix_channel_conversation_bindings_lease_expires_at",
        "uq_channel_conversation_bindings_active_conversation",
    }
    active_index = next(
        index
        for index in binding.indexes
        if index.name == "uq_channel_conversation_bindings_active_conversation"
    )
    assert active_index.unique is True
    assert active_index.dialect_options["postgresql"]["where"].text == "status = 'ACTIVE'"


def test_delivery_metadata_declares_bounded_attempt_lifecycle_and_indexes() -> None:
    delivery = ChannelOutboundDelivery.__table__

    assert set(delivery.columns.keys()) == {
        "id",
        "channel_kind",
        "binding_id",
        "exchange_id",
        "delivery_hmac",
        "status",
        "safe_error_code",
        "attempt_count",
        "created_at",
        "sending_at",
        "completed_at",
    }
    assert isinstance(delivery.c.id.type, UUID)
    assert delivery.c.channel_kind.type.length == 32
    assert isinstance(delivery.c.delivery_hmac.type, CHAR)
    assert delivery.c.delivery_hmac.type.length == 64
    assert delivery.c.status.type.length == 16
    assert delivery.c.safe_error_code.type.length == 64
    assert isinstance(delivery.c.attempt_count.type, SmallInteger)
    assert delivery.c.attempt_count.server_default.arg.text == "0"
    assert {
        (constraint.name, tuple(constraint.columns.keys()))
        for constraint in delivery.constraints
        if isinstance(constraint, UniqueConstraint)
    } == {
        (
            "uq_channel_outbound_deliveries_channel_binding_exchange",
            ("channel_kind", "binding_id", "exchange_id"),
        ),
        (
            "uq_channel_outbound_deliveries_channel_delivery_hmac",
            ("channel_kind", "delivery_hmac"),
        ),
    }
    assert _checks(delivery) == {
        "ck_channel_outbound_deliveries_channel_kind": "channel_kind = 'ZALO_OFFICIAL_BOT'",
        "ck_channel_outbound_deliveries_delivery_hmac": "delivery_hmac ~ '^[0-9a-f]{64}$'",
        "ck_channel_outbound_deliveries_safe_error_code": (
            "safe_error_code IS NULL OR safe_error_code ~ '^[A-Z][A-Z0-9_]{0,63}$'"
        ),
        "ck_channel_outbound_deliveries_status": (
            "status IN ('PENDING', 'SENDING', 'SENT', 'FAILED', 'UNKNOWN', 'ABANDONED')"
        ),
        "ck_channel_outbound_deliveries_attempt_count_range": "attempt_count BETWEEN 0 AND 1",
        "ck_channel_outbound_deliveries_status_shape": (
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
            "OR (attempt_count = 1 AND sending_at IS NOT NULL)))"
        ),
    }
    assert {
        foreign_key.parent.name: (foreign_key.target_fullname, foreign_key.ondelete)
        for foreign_key in delivery.foreign_keys
    } == {
        "binding_id": ("channel_conversation_bindings.id", "CASCADE"),
        "exchange_id": ("conversation_exchanges.id", "CASCADE"),
    }
    assert {index.name for index in delivery.indexes} == {
        "ix_channel_outbound_deliveries_binding_created_at",
        "ix_channel_outbound_deliveries_status_created_at",
        "uq_channel_outbound_deliveries_sending_binding",
    }
    sending_index = next(
        index
        for index in delivery.indexes
        if index.name == "uq_channel_outbound_deliveries_sending_binding"
    )
    assert sending_index.unique is True
    assert sending_index.dialect_options["postgresql"]["where"].text == "status = 'SENDING'"


def test_channel_relationships_do_not_add_reverse_core_cascades() -> None:
    assert "delete-orphan" in ChannelConversationBinding.outbound_deliveries.property.cascade
    assert ChannelConversationBinding.outbound_deliveries.property.passive_deletes is True
    assert {
        relationship.mapper.class_.__module__
        for relationship in ChannelConversationBinding.__mapper__.relationships
    } == {"legal_chatbot.channels.orm"}
    assert {
        relationship.mapper.class_.__module__
        for relationship in ChannelOutboundDelivery.__mapper__.relationships
    } == {"legal_chatbot.channels.orm"}
    assert not hasattr(Conversation, "channel_conversation_bindings")
    assert not hasattr(ConversationExchange, "channel_outbound_deliveries")


def test_schema_and_migration_do_not_reference_zalo_personal_bridge() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    forbidden_literal = "ZALO_PERSONAL_BRIDGE"

    for path in (
        repository_root / "src/legal_chatbot/channels/orm.py",
        repository_root / "alembic/versions/0005_channel_delivery.py",
    ):
        assert forbidden_literal not in path.read_text(encoding="utf-8")
