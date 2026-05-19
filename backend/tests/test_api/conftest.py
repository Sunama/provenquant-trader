"""
Shared fixtures for API (HTTP) integration tests.
Requires Postgres at localhost:5432 with the trader_test database and tables created.
Run after `alembic upgrade head` on the test DB.
"""
from __future__ import annotations

import os
import socket

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text

import app.db.base  # noqa: F401 — ensure all ORM models are registered
from app.db.session import SessionLocal

AUTH_HEADERS = {"Authorization": "Bearer test-api-key"}

_TRUNCATE_SQL = text(
    "TRUNCATE strategy_assets, strategy_exchange_refs, trade_history, "
    "positions, strategy_configs, exchange_accounts, watched_assets, "
    "app_settings CASCADE"
)


def _postgres_available() -> bool:
    try:
        s = socket.create_connection(("localhost", 5432), timeout=1.0)
        s.close()
        return True
    except OSError:
        return False


needs_db = pytest.mark.skipif(
    not _postgres_available(),
    reason="Postgres not reachable at localhost:5432 (start Docker services)",
)


@pytest.fixture
async def db():
    """Async DB session targeting the trader_test database."""
    async with SessionLocal() as session:
        yield session


@pytest.fixture
async def client():
    """httpx AsyncClient wired to the FastAPI app with API-key auth headers."""
    from main import app
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=AUTH_HEADERS,
    ) as ac:
        yield ac


@pytest.fixture(autouse=True)
async def clean_tables():
    """Truncate all application tables after every test to ensure isolation."""
    yield
    try:
        async with SessionLocal() as session:
            await session.execute(_TRUNCATE_SQL)
            await session.commit()
    except Exception:
        pass
