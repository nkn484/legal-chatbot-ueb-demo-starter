"""Async SQLAlchemy engine and session factory construction."""

from collections.abc import Callable

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from legal_chatbot.core.config import Settings

SessionFactory = Callable[[], AsyncSession]


def create_engine(settings: Settings) -> AsyncEngine:
    """Create the application's async engine with bounded connection establishment."""
    return create_async_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        connect_args={"timeout": settings.database_connect_timeout_seconds},
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create non-expiring sessions suitable for explicit async unit-of-work boundaries."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
