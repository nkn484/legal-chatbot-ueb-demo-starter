"""Bounded PostgreSQL and pgvector readiness probe."""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class DatabaseReadiness:
    """Check that PostgreSQL is reachable and the pgvector extension is installed."""

    def __init__(self, engine: AsyncEngine, timeout_seconds: float) -> None:
        self._engine = engine
        self._timeout_seconds = timeout_seconds

    async def check(self) -> bool:
        """Return true only when a bounded probe confirms PostgreSQL and pgvector."""
        async with asyncio.timeout(self._timeout_seconds):
            async with self._engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
                result = await connection.execute(
                    text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
                )
                return bool(result.scalar_one())
