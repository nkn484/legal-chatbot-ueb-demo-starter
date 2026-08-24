"""Unit coverage for M06 chat structured logging safety."""

import json
import logging

import pytest

from legal_chatbot.core.logging import LOG_FIELDS, JsonFormatter

M06_LOG_FIELDS = {
    "chat_outcome",
    "chat_reason",
    "chat_provider_called",
    "chat_citation_count",
    "chat_error_code",
    "chat_provider_output_class",
}


@pytest.mark.parametrize(
    ("event", "extra"),
    [
        (
            "grounded_chat_complete",
            {
                "request_id": "request-1",
                "provider": "shine_shop",
                "model": "demo-model",
                "operation": "grounded_chat",
                "retrieval_run_id": "run-1",
                "retrieval_citation_count": 2,
                "chat_outcome": "completed",
                "chat_provider_called": True,
                "chat_citation_count": 2,
            },
        ),
        (
            "grounded_chat_failed",
            {
                "request_id": "request-2",
                "provider": "shine_shop",
                "operation": "grounded_chat",
                "retrieval_run_id": "run-2",
                "chat_outcome": "failed",
                "chat_reason": "provider_unavailable",
                "chat_provider_called": True,
                "chat_error_code": "provider_unavailable",
                "chat_provider_output_class": "JSON_SYNTAX",
            },
        ),
    ],
)
def test_m06_static_events_serialize_approved_existing_and_chat_fields_with_nulls(
    event: str, extra: dict[str, object]
) -> None:
    payload = json.loads(JsonFormatter().format(logging.makeLogRecord({"msg": event, **extra})))

    assert set(payload) == set(LOG_FIELDS)
    assert payload["message"] == event
    assert {field: payload[field] for field in extra} == extra
    assert all(payload[field] is None for field in M06_LOG_FIELDS - extra.keys())


@pytest.mark.parametrize("event", ["grounded_chat_complete", "grounded_chat_failed"])
def test_m06_static_events_exclude_unapproved_sensitive_extras(event: str) -> None:
    sentinels = {
        "raw_question": "RAW_QUESTION_SENTINEL",
        "question_hash": "QUESTION_HASH_SENTINEL",
        "prompt": "PROMPT_SENTINEL",
        "excerpt_text": "EXCERPT_TEXT_SENTINEL",
        "chunk_text": "CHUNK_TEXT_SENTINEL",
        "model_response": "MODEL_RESPONSE_SENTINEL",
        "provider_body": "PROVIDER_BODY_SENTINEL",
        "sql": "SQL_SENTINEL",
        "exception_text": "EXCEPTION_TEXT_SENTINEL",
    }
    payload = json.loads(
        JsonFormatter().format(
            logging.makeLogRecord(
                {
                    "msg": event,
                    "chat_outcome": "completed" if event.endswith("complete") else "failed",
                    **sentinels,
                }
            )
        )
    )

    serialized = json.dumps(payload)
    assert payload["message"] == event
    assert all(sentinel not in serialized for sentinel in sentinels.values())
    assert not sentinels.keys() & payload.keys()
