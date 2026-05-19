"""
Root conftest — sets all required environment variables BEFORE any app.* import
so that pydantic-settings can construct Settings() without a real .env file.
"""
import os

# Must be set before the first `from app.core.settings import settings` is executed.
_defaults = {
    "API_KEY": "test-api-key",
    "SERVER_SECRET": "test-secret-key-for-unit-testing-only",
    "POSTGRES_PASSWORD": "testpass",
    "TRADER_POSTGRES_USER": "trader",
    "TRADER_POSTGRES_PASSWORD": "testpass",
    "TRADER_POSTGRES_DB": "trader_test",
    "REDIS_USERNAME": "",
    "REDIS_PASSWORD": "testpass",
    "REDIS_HOST": "localhost",
    "REDIS_PORT": "6379",
    "REDIS_URL": "redis://:testpass@localhost:6379/15",
    "DATABASE_URL": "postgresql+psycopg://trader:testpass@localhost:5432/trader_test",
    "RABBITMQ_USER": "guest",
    "RABBITMQ_PASSWORD": "guest",
    "RABBITMQ_HOST": "localhost",
    "RABBITMQ_PORT": "5672",
}
for key, value in _defaults.items():
    os.environ.setdefault(key, value)

import pytest
from unittest.mock import AsyncMock
import app.db.base  # noqa: F401 — registers all ORM models before any test instantiates them
from app.services.data_fetcher import TickData


# ── Shared fixtures ───────────────────────────────────────────────────

@pytest.fixture
def make_tick():
    """Factory: create a TickData with sensible defaults."""
    def _factory(
        close: float = 50_000.0,
        symbol: str = "btcusdt",
        timeframe: str = "30m",
        **overrides,
    ) -> TickData:
        return TickData(
            symbol=symbol,
            timeframe=timeframe,
            time=1_700_000_000_000,
            open=overrides.get("open", close),
            high=overrides.get("high", close * 1.001),
            low=overrides.get("low", close * 0.999),
            close=close,
            volume=overrides.get("volume", 100.0),
        )
    return _factory


@pytest.fixture
def mock_redis() -> AsyncMock:
    """AsyncMock of a redis.asyncio.Redis client."""
    r = AsyncMock()
    r.lpush = AsyncMock(return_value=1)
    r.ltrim = AsyncMock(return_value=True)
    r.publish = AsyncMock(return_value=1)
    r.set = AsyncMock(return_value=True)
    r.get = AsyncMock(return_value=None)
    r.keys = AsyncMock(return_value=[])
    r.lrange = AsyncMock(return_value=[])
    r.delete = AsyncMock(return_value=1)
    r.incrbyfloat = AsyncMock(return_value=10_000.0)
    r.xadd = AsyncMock(return_value="1700000000000-0")
    r.xreadgroup = AsyncMock(return_value=None)
    r.xack = AsyncMock(return_value=1)
    r.xgroup_create = AsyncMock(return_value=True)
    r.aclose = AsyncMock()
    return r
