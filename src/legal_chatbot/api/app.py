"""FastAPI application factory and operational endpoints."""

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Protocol

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncEngine

from legal_chatbot.channels.config import ChannelSettings
from legal_chatbot.channels.errors import ChannelError, ChannelErrorCode
from legal_chatbot.channels.models import ChannelInboundMessage, ChannelIngressReceipt
from legal_chatbot.channels.port import ChannelIngressPort
from legal_chatbot.channels.recipients import OfficialBotRecipientRegistry
from legal_chatbot.channels.webhook import install_official_bot_webhook
from legal_chatbot.core.config import Settings
from legal_chatbot.core.errors import get_request_id, register_error_handlers
from legal_chatbot.core.logging import configure_logging, get_logger
from legal_chatbot.db.readiness import DatabaseReadiness
from legal_chatbot.db.session import create_engine


class ReadinessProbe(Protocol):
    """Minimal seam for the database readiness dependency."""

    async def check(self) -> bool: ...


class ChannelRuntimePort(Protocol):
    """The lifecycle surface the API needs from an enabled channel runtime."""

    ingress: ChannelIngressPort
    recipients: OfficialBotRecipientRegistry

    async def aclose(self) -> None: ...


type ChannelRuntimeFactory = Callable[[AsyncEngine], Awaitable[ChannelRuntimePort | None]]


class _DeferredChannelIngress(ChannelIngressPort):
    """Route-stable ingress seam that is unavailable until runtime composition completes."""

    def __init__(self) -> None:
        self._ingress: ChannelIngressPort | None = None

    def bind(self, ingress: ChannelIngressPort) -> None:
        self._ingress = ingress

    def unbind(self) -> None:
        self._ingress = None

    async def handle_inbound(
        self, message: ChannelInboundMessage, now: datetime
    ) -> ChannelIngressReceipt:
        ingress = self._ingress
        if ingress is None:
            raise ChannelError(ChannelErrorCode.CHANNEL_UNAVAILABLE)
        return await ingress.handle_inbound(message, now)


def create_app(
    *,
    settings: Settings | None = None,
    engine: AsyncEngine | None = None,
    readiness: ReadinessProbe | None = None,
    channel_settings: ChannelSettings | None = None,
    channel_ingress: ChannelIngressPort | None = None,
    channel_runtime_factory: ChannelRuntimeFactory | None = None,
) -> FastAPI:
    """Build the application without loading required runtime config during import."""

    channel_enabled = channel_settings is not None and channel_settings.enabled

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        resolved_settings = settings if settings is not None else Settings()
        configure_logging(resolved_settings.log_level)
        resolved_engine = engine
        owns_engine = resolved_engine is None
        if resolved_engine is None:
            resolved_engine = create_engine(resolved_settings)
        application.state.settings = resolved_settings
        application.state.engine = resolved_engine
        application.state.readiness = readiness or DatabaseReadiness(
            resolved_engine, resolved_settings.database_readiness_timeout_seconds
        )
        deferred_ingress: _DeferredChannelIngress | None = getattr(
            application.state, "deferred_channel_ingress", None
        )
        runtime: ChannelRuntimePort | None = None
        application.state.runtime_ready = False
        try:
            if channel_enabled and channel_runtime_factory is not None:
                runtime = await channel_runtime_factory(resolved_engine)
                if runtime is None or deferred_ingress is None:
                    raise RuntimeError("M08_RUNTIME_UNAVAILABLE")
                deferred_ingress.bind(runtime.ingress)
                application.state.channel_recipients.bind(runtime.recipients)
            application.state.runtime_ready = True
            yield
        finally:
            application.state.runtime_ready = False
            if deferred_ingress is not None:
                deferred_ingress.unbind()
            recipients = getattr(application.state, "channel_recipients", None)
            if isinstance(recipients, OfficialBotRecipientRegistry):
                recipients.unbind()
            try:
                if runtime is not None:
                    await runtime.aclose()
            finally:
                if owns_engine:
                    await resolved_engine.dispose()

    application = FastAPI(lifespan=lifespan)
    register_error_handlers(application)
    if channel_enabled:
        assert channel_settings is not None
        if (channel_ingress is None) == (channel_runtime_factory is None):
            raise ValueError()
        if channel_runtime_factory is None:
            if channel_ingress is None:
                raise ValueError()
            install_official_bot_webhook(
                application,
                channel_ingress,
                channel_settings,
                OfficialBotRecipientRegistry(),
            )
        else:
            deferred_ingress = _DeferredChannelIngress()
            application.state.deferred_channel_ingress = deferred_ingress
            recipients = OfficialBotRecipientRegistry()
            application.state.channel_recipients = recipients
            install_official_bot_webhook(
                application, deferred_ingress, channel_settings, recipients
            )

    @application.middleware("http")
    async def request_logging(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)  # type: ignore[operator]
            status_code = response.status_code
        except Exception:
            # This outer middleware must return the fixed response so all responses receive an ID.
            # It intentionally does not log exception data or request content.
            response = JSONResponse(
                status_code=500,
                content={
                    "request_id": get_request_id(request),
                    "error": {"code": "internal_error", "message": "Internal server error"},
                },
            )
        duration_ms = round((time.perf_counter() - start) * 1000, 3)
        route = getattr(request.scope.get("route"), "path", "unmatched")
        outcome = (
            "success"
            if status_code < 400
            else "client_error"
            if status_code < 500
            else "server_error"
        )
        get_logger().info(
            "request_complete",
            extra={
                "request_id": request_id,
                "method": request.method,
                "route": route,
                "status_code": status_code,
                "duration_ms": duration_ms,
                "outcome": outcome,
            },
        )
        response.headers["X-Request-ID"] = request_id
        return response

    @application.get("/live")
    async def live() -> dict[str, str]:
        return {"status": "live"}

    @application.get("/ready")
    async def ready(request: Request) -> Response:
        probe = getattr(request.app.state, "readiness", None)
        if probe is None:
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        try:
            is_ready = await probe.check()
        except Exception:
            get_logger().warning("readiness_check_failed", extra={"outcome": "server_error"})
            is_ready = False
        if not is_ready:
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        if channel_enabled and not getattr(request.app.state, "runtime_ready", False):
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        return JSONResponse(status_code=200, content={"status": "ready"})

    return application


app = create_app()
