"""Metadata-only checks for bounded conversation persistence."""

from sqlalchemy import CHAR, CheckConstraint, Integer, PrimaryKeyConstraint, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from legal_chatbot.conversation.orm import (
    Conversation,
    ConversationExchange,
    ConversationExchangeReference,
)
from legal_chatbot.db.base import Base
from legal_chatbot.documents import orm as documents_orm


def _checks(table) -> set[str]:
    return {
        constraint.sqltext.text
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }


def test_conversation_tables_are_registered_on_base_metadata() -> None:
    assert {
        "conversations",
        "conversation_exchanges",
        "conversation_exchange_references",
    } <= set(Base.metadata.tables)
    assert documents_orm.RetrievalRun.__table__.name == "retrieval_runs"


def test_conversation_metadata_declares_state_bounds_and_indexes() -> None:
    conversation = Conversation.__table__

    assert set(conversation.columns.keys()) == {
        "id",
        "state_version",
        "rolling_summary",
        "active_topic",
        "created_at",
        "updated_at",
        "expires_at",
        "deleted_at",
    }
    assert isinstance(conversation.c.id.type, UUID)
    assert isinstance(conversation.c.state_version.type, Integer)
    assert conversation.c.state_version.server_default.arg.text == "0"
    assert conversation.c.rolling_summary.type.length == 1500
    assert conversation.c.active_topic.type.length == 256
    assert _checks(conversation) == {
        "state_version >= 0",
        "expires_at > created_at",
    }
    assert {index.name for index in conversation.indexes} == {
        "ix_conversations_expires_at",
        "ix_conversations_updated_at",
    }


def test_exchange_metadata_declares_idempotency_lifecycle_and_retrieval_fk() -> None:
    exchange = ConversationExchange.__table__

    assert set(exchange.columns.keys()) == {
        "id",
        "conversation_id",
        "delivery_key_sha256",
        "ordinal",
        "status",
        "lease_expires_at",
        "user_text",
        "assistant_text",
        "chat_outcome",
        "chat_reason",
        "retrieval_run_id",
        "provider",
        "model",
        "request_id",
        "created_at",
        "completed_at",
    }
    assert isinstance(exchange.c.id.type, UUID)
    assert isinstance(exchange.c.delivery_key_sha256.type, CHAR)
    assert exchange.c.delivery_key_sha256.type.length == 64
    assert isinstance(exchange.c.user_text.type, Text)
    assert isinstance(exchange.c.assistant_text.type, Text)
    assert exchange.c.status.type.length == 16
    assert exchange.c.chat_outcome.type.length == 16
    assert exchange.c.chat_reason.type.length == 64
    assert {
        column.type.length
        for column in (exchange.c.provider, exchange.c.model, exchange.c.request_id)
    } == {128}
    assert {
        frozenset(constraint.columns.keys())
        for constraint in exchange.constraints
        if isinstance(constraint, UniqueConstraint)
    } == {
        frozenset({"conversation_id", "delivery_key_sha256"}),
        frozenset({"conversation_id", "ordinal"}),
    }
    exchange_checks = _checks(exchange)
    assert {
        "delivery_key_sha256 ~ '^[0-9a-f]{64}$'",
        "ordinal > 0",
        "status IN ('PROCESSING', 'COMPLETED', 'FAILED', 'ABANDONED')",
        "char_length(user_text) BETWEEN 1 AND 4000",
        "assistant_text IS NULL OR char_length(assistant_text) BETWEEN 1 AND 4000",
        "chat_outcome IS NULL OR chat_outcome IN ('ANSWER', 'CLARIFICATION', 'REFUSAL')",
    } <= exchange_checks
    checks_by_name = {
        constraint.name: constraint.sqltext.text
        for constraint in exchange.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        name: checks_by_name[name]
        for name in (
            "ck_conversation_exchanges_status_shape",
            "ck_conversation_exchanges_completed_result_shape",
            "ck_conversation_exchanges_failure_reason",
        )
    } == {
        "ck_conversation_exchanges_status_shape": (
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
            "AND request_id IS NULL)"
        ),
        "ck_conversation_exchanges_completed_result_shape": (
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
            "'CITATION_REVALIDATION_FAILURE') AND retrieval_run_id IS NOT NULL)))"
        ),
        "ck_conversation_exchanges_failure_reason": (
            "status NOT IN ('FAILED', 'ABANDONED') "
            "OR chat_reason IS NULL "
            "OR chat_reason IN ('LEASE_EXPIRED', 'PROCESSING_FAILED', 'ABANDONED_BY_SYSTEM')"
        ),
    }
    assert {
        foreign_key.parent.name: (foreign_key.target_fullname, foreign_key.ondelete)
        for foreign_key in exchange.foreign_keys
    } == {
        "conversation_id": ("conversations.id", "CASCADE"),
        "retrieval_run_id": ("retrieval_runs.id", "RESTRICT"),
    }
    assert {index.name for index in exchange.indexes} == {
        "ix_conversation_exchanges_conversation_created_at",
        "ix_conversation_exchanges_lease_expires_at",
        "uq_conversation_exchanges_processing_conversation",
    }
    processing_index = next(
        index
        for index in exchange.indexes
        if index.name == "uq_conversation_exchanges_processing_conversation"
    )
    assert processing_index.unique
    assert processing_index.dialect_options["postgresql"]["where"].text == "status = 'PROCESSING'"


def test_exchange_reference_metadata_has_bounded_unlinked_references() -> None:
    reference = ConversationExchangeReference.__table__

    assert set(reference.columns.keys()) == {"exchange_id", "kind", "reference_id", "ordinal"}
    assert isinstance(reference.c.reference_id.type, UUID)
    assert any(
        isinstance(constraint, PrimaryKeyConstraint)
        and set(constraint.columns.keys()) == {"exchange_id", "kind", "ordinal"}
        for constraint in reference.constraints
    )
    assert any(
        isinstance(constraint, UniqueConstraint)
        and set(constraint.columns.keys()) == {"exchange_id", "kind", "reference_id"}
        for constraint in reference.constraints
    )
    assert _checks(reference) == {
        "kind IN ('CITATION', 'DOCUMENT')",
        "ordinal BETWEEN 0 AND 5",
    }
    assert {
        foreign_key.parent.name: (foreign_key.target_fullname, foreign_key.ondelete)
        for foreign_key in reference.foreign_keys
    } == {"exchange_id": ("conversation_exchanges.id", "CASCADE")}
    assert {index.name for index in reference.indexes} == {
        "ix_conversation_exchange_references_reference_id"
    }


def test_m07_relationships_cascade_only_inside_conversation_schema() -> None:
    assert "delete-orphan" in Conversation.exchanges.property.cascade
    assert Conversation.exchanges.property.passive_deletes is True
    assert "delete-orphan" in ConversationExchange.references.property.cascade
    assert ConversationExchange.references.property.passive_deletes is True
    assert not hasattr(ConversationExchange, "retrieval_run")
    assert not any(
        relationship.mapper.class_.__module__ == "legal_chatbot.documents.orm"
        for relationship in ConversationExchange.__mapper__.relationships
    )
