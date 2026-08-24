"""Small JSON-only logging configuration for safe operational events."""

import json
import logging
from datetime import UTC, datetime
from typing import Any, TextIO

LOG_FIELDS = (
    "timestamp",
    "level",
    "logger",
    "message",
    "request_id",
    "method",
    "route",
    "status_code",
    "duration_ms",
    "outcome",
    "provider",
    "model",
    "operation",
    "provider_request_id",
    "retry_count",
    "retryable",
    "source",
    "transport",
    "source_operation",
    "source_document_id",
    "provenance_type",
    "document_id",
    "document_version_id",
    "ingestion_outcome",
    "chunk_count",
    "embedding_count",
    "embedding_model_id",
    "semantic_ready",
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
    "retrieval_planner_enabled",
    "retrieval_planner_called",
    "retrieval_planner_outcome",
    "retrieval_planner_query_count",
    "retrieval_planner_duration_ms",
    "citation_id",
    "chat_outcome",
    "chat_reason",
    "chat_provider_called",
    "chat_citation_count",
    "chat_error_code",
    "chat_provider_output_class",
    "conversation_status",
    "conversation_reason",
    "conversation_ordinal",
    "conversation_state_version",
    "conversation_recent_turn_count",
    "conversation_reference_count",
    "conversation_error_code",
    "channel_kind",
    "channel_status",
    "channel_ingress_status",
    "channel_delivery_status",
    "channel_duplicate",
    "channel_citation_count",
    "channel_error_code",
)
_HANDLER_MARKER = "_legal_chatbot_json_handler"


class JsonFormatter(logging.Formatter):
    """Render only the fixed operational fields as a UTC JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        values: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        values.update({field: getattr(record, field, None) for field in LOG_FIELDS[4:]})
        return json.dumps(values, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO", *, stream: TextIO | None = None) -> None:
    """Install one JSON root handler and route Uvicorn operational logs through it."""
    root = logging.getLogger()
    root.setLevel(level)
    handler = next((item for item in root.handlers if getattr(item, _HANDLER_MARKER, False)), None)
    if handler is None:
        handler = logging.StreamHandler(stream)
        setattr(handler, _HANDLER_MARKER, True)
    elif stream is not None and isinstance(handler, logging.StreamHandler):
        handler.setStream(stream)

    # Deliberately replace all root handlers: mixed plaintext/JSON output can leak operational data.
    for existing_handler in tuple(root.handlers):
        root.removeHandler(existing_handler)
    root.addHandler(handler)
    handler.setLevel(level)
    handler.setFormatter(JsonFormatter())

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    for logger_name in ("httpx", "httpcore"):
        http_logger = logging.getLogger(logger_name)
        http_logger.setLevel(logging.WARNING)
        http_logger.handlers.clear()
        http_logger.propagate = True


def get_logger() -> logging.Logger:
    """Return the foundation logger; callers only emit predefined operational events."""
    return logging.getLogger("legal_chatbot")
