"""
API tests for /api/strategies endpoints.
Covers: list, get, create, update, delete, toggle, and class discovery.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.db.models.strategy_config import StrategyConfig
from tests.test_api.conftest import needs_db

pytestmark = [pytest.mark.integration, needs_db]

# Patch _notify_trader for all tests in this module — it publishes to Redis
# which is not required for these DB-focused tests.
_NOTIFY_PATCH = "app.api.strategies._notify_trader"

_BASE_BODY = {
    "name": "My Strategy",
    "strategy_class": "strategies.example.MyStrategy",
    "description": "Test",
    "enabled": True,
    "is_paper": True,
    "params": {},
    "assets": [],
    "exchange_accounts": [],
}


# ── GET /api/strategies/ ──────────────────────────────────────────────────────

async def test_list_strategies_empty(client):
    r = await client.get("/api/strategies/")
    assert r.status_code == 200
    assert r.json() == []


async def test_list_strategies_returns_all(client, db):
    db.add(StrategyConfig(
        id="s1", name="Alpha", strategy_class="strategies.x.Alpha",
        enabled=True, is_paper=True, params={},
    ))
    db.add(StrategyConfig(
        id="s2", name="Beta", strategy_class="strategies.x.Beta",
        enabled=False, is_paper=True, params={},
    ))
    await db.commit()

    r = await client.get("/api/strategies/")
    assert r.status_code == 200
    assert len(r.json()) == 2


# ── GET /api/strategies/{id} ─────────────────────────────────────────────────

async def test_get_strategy_not_found(client):
    r = await client.get("/api/strategies/nonexistent-id")
    assert r.status_code == 404


async def test_get_strategy(client, db):
    db.add(StrategyConfig(
        id="s1", name="Alpha", strategy_class="strategies.x.Alpha",
        enabled=True, is_paper=True, params={"rsi_period": 14},
    ))
    await db.commit()

    r = await client.get("/api/strategies/s1")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == "s1"
    assert data["name"] == "Alpha"
    assert data["enabled"] is True
    assert data["params"] == {"rsi_period": 14}
    assert data["assets"] == []


# ── POST /api/strategies/ ─────────────────────────────────────────────────────

async def test_create_strategy_no_assets(client):
    with patch(_NOTIFY_PATCH, new_callable=AsyncMock):
        r = await client.post("/api/strategies/", json=_BASE_BODY)

    assert r.status_code == 201
    data = r.json()
    assert "id" in data
    assert data["name"] == "My Strategy"


async def test_create_strategy_duplicate_name_returns_409(client):
    with patch(_NOTIFY_PATCH, new_callable=AsyncMock):
        await client.post("/api/strategies/", json=_BASE_BODY)
        r = await client.post("/api/strategies/", json=_BASE_BODY)

    assert r.status_code == 409


async def test_create_strategy_with_asset(client):
    """Strategy creation with one asset calls validate_symbol and stores base/quote."""
    from app.services.symbol_validator import SymbolInfo

    body = {
        **_BASE_BODY,
        "name": "With Asset",
        "assets": [{
            "symbol": "BTCUSDT",
            "exchange": "binance",
            "timeframe": "30m",
            "market_type": "futures",
            "transaction_fee": 0.0004,
            "leverage": 1.0,
        }],
    }
    mock_info = SymbolInfo(
        symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT",
        exchange="binance", market_type="futures",
    )

    with (
        patch("app.api.strategies.validate_symbol", new_callable=AsyncMock, return_value=mock_info),
        patch(_NOTIFY_PATCH, new_callable=AsyncMock),
    ):
        r = await client.post("/api/strategies/", json=body)

    assert r.status_code == 201


async def test_create_strategy_invalid_symbol_returns_422(client):
    """validate_symbol returning None triggers 422."""
    body = {
        **_BASE_BODY,
        "name": "Bad Symbol",
        "assets": [{
            "symbol": "INVALID",
            "exchange": "binance",
            "timeframe": "30m",
            "market_type": "futures",
        }],
    }
    with (
        patch("app.api.strategies.validate_symbol", new_callable=AsyncMock, return_value=None),
        patch(_NOTIFY_PATCH, new_callable=AsyncMock),
    ):
        r = await client.post("/api/strategies/", json=body)

    assert r.status_code == 422


# ── PUT /api/strategies/{id} ─────────────────────────────────────────────────

async def test_update_strategy_name(client, db):
    db.add(StrategyConfig(
        id="s1", name="Old Name", strategy_class="strategies.x.X",
        enabled=True, is_paper=True, params={},
    ))
    await db.commit()

    with patch(_NOTIFY_PATCH, new_callable=AsyncMock):
        r = await client.put("/api/strategies/s1", json={"name": "New Name"})

    assert r.status_code == 200
    # Verify via GET
    with patch(_NOTIFY_PATCH, new_callable=AsyncMock):
        r2 = await client.get("/api/strategies/s1")
    assert r2.json()["name"] == "New Name"


async def test_update_strategy_not_found(client):
    with patch(_NOTIFY_PATCH, new_callable=AsyncMock):
        r = await client.put("/api/strategies/nonexistent", json={"name": "X"})
    assert r.status_code == 404


async def test_update_strategy_params(client, db):
    db.add(StrategyConfig(
        id="s1", name="S1", strategy_class="strategies.x.X",
        enabled=True, is_paper=True, params={"old_key": 1},
    ))
    await db.commit()

    with patch(_NOTIFY_PATCH, new_callable=AsyncMock):
        r = await client.put("/api/strategies/s1", json={"params": {"new_key": 42}})

    assert r.status_code == 200
    r2 = await client.get("/api/strategies/s1")
    assert r2.json()["params"] == {"new_key": 42}


# ── DELETE /api/strategies/{id} ──────────────────────────────────────────────

async def test_delete_strategy(client, db):
    db.add(StrategyConfig(
        id="s1", name="To Delete", strategy_class="strategies.x.X",
        enabled=True, is_paper=True, params={},
    ))
    await db.commit()

    with patch(_NOTIFY_PATCH, new_callable=AsyncMock):
        r = await client.delete("/api/strategies/s1")
    assert r.status_code == 204

    r2 = await client.get("/api/strategies/s1")
    assert r2.status_code == 404


async def test_delete_strategy_not_found(client):
    with patch(_NOTIFY_PATCH, new_callable=AsyncMock):
        r = await client.delete("/api/strategies/nonexistent")
    assert r.status_code == 404


# ── PATCH /api/strategies/{id}/toggle ────────────────────────────────────────

async def test_toggle_strategy_enable_disable(client, db):
    db.add(StrategyConfig(
        id="s1", name="S1", strategy_class="strategies.x.X",
        enabled=True, is_paper=True, params={},
    ))
    await db.commit()

    with patch(_NOTIFY_PATCH, new_callable=AsyncMock):
        r = await client.patch("/api/strategies/s1/toggle")
    assert r.status_code == 200
    assert r.json()["enabled"] is False

    with patch(_NOTIFY_PATCH, new_callable=AsyncMock):
        r2 = await client.patch("/api/strategies/s1/toggle")
    assert r2.json()["enabled"] is True


async def test_toggle_strategy_not_found(client):
    with patch(_NOTIFY_PATCH, new_callable=AsyncMock):
        r = await client.patch("/api/strategies/nonexistent/toggle")
    assert r.status_code == 404


# ── GET /api/strategies/classes ──────────────────────────────────────────────

async def test_list_strategy_classes_returns_list(client):
    """Should return a list (empty if no strategies/ directory or no subclasses)."""
    r = await client.get("/api/strategies/classes")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
