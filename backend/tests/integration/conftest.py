"""
Integration test fixtures.
These tests require running Redis and Postgres services.
Skip automatically if REDIS_URL or DATABASE_URL is not reachable.
"""
import os
import pytest
import asyncio
import socket


def _host_reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except OSError:
        return False


def _redis_available() -> bool:
    return _host_reachable(
        os.getenv("REDIS_HOST", "localhost"),
        int(os.getenv("REDIS_PORT", "6379")),
    )


def _postgres_available() -> bool:
    return _host_reachable("localhost", 5432)


needs_redis = pytest.mark.skipif(
    not _redis_available(),
    reason="Redis not reachable (start Docker services)",
)

needs_db = pytest.mark.skipif(
    not _postgres_available(),
    reason="Postgres not reachable (start Docker services)",
)


@pytest.fixture
async def redis_client():
    """Fresh Redis client using database 15 (test isolation)."""
    import redis.asyncio as aioredis
    from app.core.settings import settings
    url = settings.REDIS_URL.replace("/0", "/15")  # use DB 15 for tests
    r = await aioredis.from_url(url, decode_responses=True)
    # Flush test DB before each test
    await r.flushdb()
    yield r
    await r.flushdb()
    await r.aclose()
