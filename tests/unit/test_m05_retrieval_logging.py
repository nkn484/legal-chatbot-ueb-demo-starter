"""Unit coverage for M05 retrieval structured logging safety."""

import json
import logging

import pytest

from legal_chatbot.core.logging import LOG_FIELDS, JsonFormatter

M05_LOG_FIELDS = {
    "retrieval_run_id",
    "retrieval_strategy",
    "retrieval_strategy_version",
    "retrieval_scope",
    "retrieval_decision",
    "retrieval_reason",
    "retrieval_candidate_count",
    "retrieval_citation_count",
    "retrieval_top_k",
    "retrieval_error_code",
    "citation_id",
}


@pytest.mark.parametrize(
    ("event", "extra"),
    [
        (
            "retrieval_complete",
            {
                "retrieval_run_id": "run-1",
                "retrieval_strategy": "semantic",
                "retrieval_strategy_version": "v1",
                "retrieval_scope": "vbqppl_read_only",
                "retrieval_decision": "completed",
                "retrieval_candidate_count": 12,
                "retrieval_citation_count": 3,
                "retrieval_top_k": 5,
            },
        ),
        (
            "retrieval_failed",
            {
                "retrieval_run_id": "run-2",
                "retrieval_strategy": "semantic",
                "retrieval_strategy_version": "v1",
                "retrieval_scope": "vbqppl_read_only",
                "retrieval_decision": "failed",
                "retrieval_reason": "source_unavailable",
                "retrieval_top_k": 5,
                "retrieval_error_code": "source_unavailable",
            },
        ),
        (
            "citation_resolved",
            {
                "retrieval_run_id": "run-3",
                "retrieval_decision": "resolved",
                "citation_id": "citation-1",
            },
        ),
        (
            "citation_resolution_failed",
            {
                "retrieval_run_id": "run-4",
                "retrieval_decision": "failed",
                "retrieval_reason": "citation_not_found",
                "retrieval_error_code": "citation_not_found",
                "citation_id": "citation-2",
            },
        ),
    ],
)
def test_m05_static_events_serialize_approved_fields_with_nulls_for_missing_fields(
    event: str, extra: dict[str, object]
) -> None:
    payload = json.loads(JsonFormatter().format(logging.makeLogRecord({"msg": event, **extra})))

    assert set(payload) == set(LOG_FIELDS)
    assert payload["message"] == event
    assert {field: payload[field] for field in extra} == extra
    assert all(payload[field] is None for field in M05_LOG_FIELDS - extra.keys())
    assert not {"raw_query", "query_hash", "chunk_text", "sql", "exception_text"} & payload.keys()


def test_m05_static_event_logging_excludes_query_chunk_and_error_sentinels() -> None:
    sentinels = {
        "raw_query": "RAW_QUERY_SENTINEL",
        "query_hash": "QUERY_HASH_SENTINEL",
        "chunk_text": "CHUNK_TEXT_SENTINEL",
        "sql": "SQL_SENTINEL",
        "exception_text": "EXCEPTION_TEXT_SENTINEL",
    }
    payload = json.loads(
        JsonFormatter().format(
            logging.makeLogRecord(
                {
                    "msg": "retrieval_failed",
                    "retrieval_run_id": "run-safe",
                    "retrieval_decision": "failed",
                    "retrieval_error_code": "source_unavailable",
                    **sentinels,
                }
            )
        )
    )
    serialized = json.dumps(payload)

    assert payload["message"] == "retrieval_failed"
    assert payload["retrieval_error_code"] == "source_unavailable"
    assert all(sentinel not in serialized for sentinel in sentinels.values())
