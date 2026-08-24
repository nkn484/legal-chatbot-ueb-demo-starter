"""Unit coverage for M01 configuration, HTTP safety, and operational plumbing."""

import io
import json
import logging

import pytest
from fastapi import Body, Request
from pydantic import ValidationError
from tests.conftest import StubReadiness, app_client

from legal_chatbot import main as main_module
from legal_chatbot.api.app import create_app
from legal_chatbot.channels.config import ChannelSettings
from legal_chatbot.core.config import Settings
from legal_chatbot.core.errors import AppError
from legal_chatbot.core.logging import configure_logging, get_logger

VALID_DSN = "postgresql+asyncpg://demo_user:secret-password@localhost:5432/demo"


def test_settings_requires_asyncpg_url_and_redacts_secret() -> None:
    settings = Settings(DATABASE_URL=VALID_DSN)
    assert "secret-password" not in repr(settings)
    assert settings.database_url.get_secret_value() == VALID_DSN


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+asyncpg://",
        "postgresql+asyncpg://demo_user:sentinel-password@/demo",
        "postgresql+asyncpg://demo_user:sentinel-password@localhost",
        "postgresql+asyncpg://:sentinel-password@localhost/demo",
        "postgresql+asyncpg://demo_user@localhost/demo",
        "postgresql://demo_user:sentinel-password@localhost/demo",
    ],
)
def test_settings_rejects_incomplete_or_wrong_driver_urls_without_leaking_secret(
    database_url: str,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(DATABASE_URL=database_url)
    error_text = str(exc_info.value)
    assert "DATABASE_URL must be a complete postgresql+asyncpg URL" in error_text
    assert "sentinel-password" not in error_text


def test_settings_loads_case_insensitive_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("database_url", VALID_DSN)
    monkeypatch.setenv("app_host", "0.0.0.0")
    monkeypatch.setenv("app_port", "9000")
    settings = Settings()
    assert settings.host == "0.0.0.0"
    assert settings.port == 9000


def test_module_entrypoint_configures_json_logging_before_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(DATABASE_URL=VALID_DSN, APP_HOST="0.0.0.0", APP_PORT=9001)
    events: list[str] = []
    captured: dict[str, object] = {}
    created_with: list[Settings] = []
    application = object()

    monkeypatch.setattr(main_module, "Settings", lambda: settings)
    monkeypatch.setattr(
        main_module, "ChannelSettings", lambda: ChannelSettings(enabled=False)
    )
    monkeypatch.setattr(
        main_module,
        "configure_logging",
        lambda level: events.append(f"logging:{level}"),
    )

    def fake_create_app(*, settings: Settings, channel_settings: ChannelSettings) -> object:
        created_with.append(settings)
        assert not channel_settings.enabled
        events.append("create_app")
        return application

    monkeypatch.setattr(
        main_module,
        "create_app",
        fake_create_app,
    )

    def fake_run(app: object, **kwargs: object) -> None:
        events.append("uvicorn.run")
        captured["application"] = app
        captured.update(kwargs)

    monkeypatch.setattr(main_module.uvicorn, "run", fake_run)

    main_module.main()

    assert events == ["logging:INFO", "create_app", "uvicorn.run"]
    assert created_with == [settings]
    assert captured == {
        "application": application,
        "host": "0.0.0.0",
        "port": 9001,
        "log_config": None,
        "access_log": False,
    }
    assert VALID_DSN not in repr(captured)
    assert VALID_DSN not in repr(events)


def test_json_logging_is_utc_fixed_field_and_idempotent() -> None:
    root = logging.getLogger()
    original_root_handlers = root.handlers[:]
    uvicorn_logger = logging.getLogger("uvicorn")
    original_uvicorn_handlers = uvicorn_logger.handlers[:]
    original_uvicorn_propagate = uvicorn_logger.propagate
    stream = io.StringIO()
    try:
        root.addHandler(logging.StreamHandler(io.StringIO()))
        uvicorn_logger.addHandler(logging.StreamHandler(io.StringIO()))
        uvicorn_logger.propagate = False
        configure_logging("INFO", stream=stream)
        configure_logging("INFO", stream=stream)
        get_logger().info("safe_event", extra={"request_id": "request-1", "outcome": "success"})
        records = [line for line in stream.getvalue().splitlines() if "safe_event" in line]
        assert len(records) == 1
        payload = json.loads(records[0])
        assert set(payload) == {
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
            "chat_provider_output_class",
            "chat_citation_count",
            "chat_error_code",
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
        }
        assert payload["timestamp"].endswith("Z")
        assert payload["request_id"] == "request-1"
        assert len(root.handlers) == 1
        assert getattr(root.handlers[0], "_legal_chatbot_json_handler", False)
        assert uvicorn_logger.handlers == []
        assert uvicorn_logger.propagate is True
    finally:
        root.handlers[:] = original_root_handlers
        uvicorn_logger.handlers[:] = original_uvicorn_handlers
        uvicorn_logger.propagate = original_uvicorn_propagate


def test_json_logging_suppresses_http_client_request_urls() -> None:
    root = logging.getLogger()
    httpx_logger = logging.getLogger("httpx")
    httpcore_logger = logging.getLogger("httpcore")
    original_root_handlers = root.handlers[:]
    original_root_level = root.level
    original_httpx_handlers = httpx_logger.handlers[:]
    original_httpx_level = httpx_logger.level
    original_httpx_propagate = httpx_logger.propagate
    original_httpcore_handlers = httpcore_logger.handlers[:]
    original_httpcore_level = httpcore_logger.level
    original_httpcore_propagate = httpcore_logger.propagate
    stream = io.StringIO()
    sentinel_url = "https://sentinel.invalid/private-path"
    try:
        httpx_logger.setLevel(logging.INFO)
        httpcore_logger.setLevel(logging.INFO)
        configure_logging("INFO", stream=stream)
        httpx_logger.info("HTTP Request: GET %s", sentinel_url)

        assert sentinel_url not in stream.getvalue()
        assert httpx_logger.level == logging.WARNING
        assert httpcore_logger.level == logging.WARNING
        assert httpx_logger.handlers == httpcore_logger.handlers == []
        assert httpx_logger.propagate is httpcore_logger.propagate is True
    finally:
        root.handlers[:] = original_root_handlers
        root.setLevel(original_root_level)
        httpx_logger.handlers[:] = original_httpx_handlers
        httpx_logger.setLevel(original_httpx_level)
        httpx_logger.propagate = original_httpx_propagate
        httpcore_logger.handlers[:] = original_httpcore_handlers
        httpcore_logger.setLevel(original_httpcore_level)
        httpcore_logger.propagate = original_httpcore_propagate


@pytest.mark.asyncio
async def test_error_handlers_are_safe_and_validation_omits_input() -> None:
    app = create_app(
        settings=Settings(DATABASE_URL=VALID_DSN), engine=object(), readiness=StubReadiness()
    )

    @app.get("/known-error")
    async def known_error() -> None:
        raise AppError(403, "forbidden", "You may not access this resource")

    @app.post("/validated")
    async def validated(value: int = Body(...)) -> dict[str, int]:
        return {"value": value}

    @app.get("/unexpected")
    async def unexpected() -> None:
        raise RuntimeError("secret-password")

    async with app_client(app) as client:
        known = await client.get("/known-error")
        validation = await client.post("/validated", json="secret-password")
        unexpected_response = await client.get("/unexpected")
    assert known.status_code == 403
    assert known.json()["error"]["code"] == "forbidden"
    assert known.json()["request_id"] == known.headers["X-Request-ID"]
    assert validation.status_code == 422
    assert validation.json()["request_id"] == validation.headers["X-Request-ID"]
    assert "secret-password" not in validation.text
    assert unexpected_response.status_code == 500
    assert unexpected_response.json() == {
        "request_id": unexpected_response.headers["X-Request-ID"],
        "error": {"code": "internal_error", "message": "Internal server error"},
    }
    assert "secret-password" not in unexpected_response.text


@pytest.mark.asyncio
async def test_live_and_ready_and_request_id() -> None:
    probe = StubReadiness(result=True)
    app = create_app(settings=Settings(DATABASE_URL=VALID_DSN), engine=object(), readiness=probe)

    @app.get("/request-state")
    async def request_state(request: Request) -> dict[str, str]:
        return {"request_id": request.state.request_id}

    async with app_client(app) as client:
        live = await client.get("/live")
        ready = await client.get("/ready")
        state = await client.get("/request-state")
    assert live.status_code == 200
    assert live.json() == {"status": "live"}
    assert probe.calls == 1
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}
    assert ready.headers["X-Request-ID"]
    assert state.json()["request_id"] == state.headers["X-Request-ID"]


@pytest.mark.asyncio
async def test_ready_returns_safe_503_when_probe_fails() -> None:
    app = create_app(
        settings=Settings(DATABASE_URL=VALID_DSN),
        engine=object(),
        readiness=StubReadiness(error=RuntimeError("secret-password")),
    )
    async with app_client(app) as client:
        response = await client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
    assert "secret-password" not in response.text
