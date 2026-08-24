"""Real PostgreSQL foundation checks, enabled only by explicit operator opt-in."""

import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from legal_chatbot.api.app import create_app
from legal_chatbot.core.config import Settings
from legal_chatbot.db.readiness import DatabaseReadiness
from legal_chatbot.db.session import create_engine

pytestmark = pytest.mark.integration

if os.getenv("RUN_INTEGRATION") != "1":
    pytest.skip(
        "set RUN_INTEGRATION=1 to run PostgreSQL integration tests", allow_module_level=True
    )


@pytest.fixture
async def settings() -> Settings:
    return Settings()


@pytest.fixture
async def engine(settings: Settings):
    database_engine = create_engine(settings)
    try:
        yield database_engine
    finally:
        await database_engine.dispose()


@pytest.mark.asyncio
async def test_postgres_vector_alembic_head_and_ready(settings: Settings, engine) -> None:
    async with engine.connect() as connection:
        assert (await connection.execute(text("SELECT 1"))).scalar_one() == 1
        assert (
            await connection.execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
            )
        ).scalar_one() is True

    alembic_environment = os.environ.copy()
    alembic_environment["DATABASE_URL"] = settings.database_url.get_secret_value()
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "current", "--check-heads"],
        cwd=Path(__file__).resolve().parents[2],
        check=False,
        capture_output=True,
        text=True,
        env=alembic_environment,
    )
    assert completed.returncode == 0, "Alembic is not at head"

    app = create_app(settings=settings, engine=engine, readiness=DatabaseReadiness(engine, 3.0))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
