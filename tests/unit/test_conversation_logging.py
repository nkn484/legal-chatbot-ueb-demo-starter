"""Unit coverage for M07 conversation structured logging safety."""

import json
import logging

import pytest

from legal_chatbot.core.logging import LOG_FIELDS, JsonFormatter

M07_LOG_FIELDS = {
    "conversation_status",
    "conversation_reason",
    "conversation_ordinal",
    "conversation_state_version",
    "conversation_recent_turn_count",
    "conversation_reference_count",
    "conversation_error_code",
}


@pytest.mark.parametrize(
    ("event", "extra"),
    [
        (
            "conversation_reserved",
            {
                "conversation_status": "RESERVED",
                "conversation_ordinal": 3,
                "conversation_state_version": 4,
                "conversation_recent_turn_count": 2,
                "conversation_reference_count": 1,
            },
        ),
        (
            "conversation_completed",
            {
                "conversation_status": "COMPLETED",
                "conversation_ordinal": 3,
                "conversation_state_version": 5,
                "conversation_recent_turn_count": 4,
                "conversation_reference_count": 2,
            },
        ),
        (
            "conversation_busy",
            {
                "conversation_status": "PROCESSING",
                "conversation_reason": "BUSY",
                "conversation_error_code": "BUSY",
            },
        ),
        (
            "conversation_conflict",
            {
                "conversation_status": "PROCESSING",
                "conversation_reason": "CONFLICT",
                "conversation_ordinal": 3,
                "conversation_state_version": 4,
                "conversation_error_code": "CONFLICT",
            },
        ),
        (
            "conversation_expired",
            {
                "conversation_status": "ABANDONED",
                "conversation_reason": "EXPIRED",
                "conversation_error_code": "EXPIRED",
            },
        ),
        (
            "conversation_failed",
            {
                "conversation_status": "FAILED",
                "conversation_reason": "STATE_INVALID",
                "conversation_ordinal": 3,
                "conversation_state_version": 4,
                "conversation_error_code": "STATE_INVALID",
            },
        ),
    ],
)
def test_m07_static_events_serialize_approved_conversation_fields_with_nulls(
    event: str, extra: dict[str, object]
) -> None:
    payload = json.loads(JsonFormatter().format(logging.makeLogRecord({"msg": event, **extra})))

    assert set(payload) == set(LOG_FIELDS)
    assert payload["message"] == event
    assert {field: payload[field] for field in extra} == extra
    assert all(payload[field] is None for field in M07_LOG_FIELDS - extra.keys())


@pytest.mark.parametrize(
    "event",
    [
        "conversation_reserved",
        "conversation_completed",
        "conversation_busy",
        "conversation_conflict",
        "conversation_expired",
        "conversation_failed",
    ],
)
def test_m07_static_events_omit_unapproved_sensitive_extras(event: str) -> None:
    sentinels = {
        "conversation_id": "CONVERSATION_ID_SENTINEL",
        "delivery_id": "DELIVERY_ID_SENTINEL",
        "delivery_digest": "DELIVERY_DIGEST_SENTINEL",
        "user_text": "USER_TEXT_SENTINEL",
        "assistant_text": "ASSISTANT_TEXT_SENTINEL",
        "rolling_summary": "SUMMARY_SENTINEL",
        "active_topic": "TOPIC_SENTINEL",
        "reference_ids": "REFERENCE_IDS_SENTINEL",
        "citation_ids": "CITATION_IDS_SENTINEL",
        "context": "CONTEXT_SENTINEL",
        "retrieval_query": "RETRIEVAL_QUERY_SENTINEL",
        "prompt": "PROMPT_SENTINEL",
        "provider_body": "PROVIDER_BODY_SENTINEL",
        "provider_output": "PROVIDER_OUTPUT_SENTINEL",
        "sql": "SQL_SENTINEL",
        "exception": "EXCEPTION_SENTINEL",
    }
    payload = json.loads(
        JsonFormatter().format(
            logging.makeLogRecord(
                {
                    "msg": event,
                    "conversation_status": "FAILED",
                    "conversation_error_code": "STATE_INVALID",
                    **sentinels,
                }
            )
        )
    )

    serialized = json.dumps(payload)
    assert payload["message"] == event
    assert all(sentinel not in serialized for sentinel in sentinels.values())
    assert not sentinels.keys() & payload.keys()
