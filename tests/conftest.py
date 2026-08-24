"""Shared test helpers only."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI


class StubReadiness:
    """Controllable readiness probe for API unit tests."""

    def __init__(self, result: bool = True, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    async def check(self) -> bool:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


@asynccontextmanager
async def app_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Run an app lifespan while exposing an in-process HTTP client."""
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
