"""
API tests for /api/trades endpoints.
Paper balance lives in Redis; these tests mock PaperTradeAdapter.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from tests.test_api.conftest import needs_db

pytestmark = [pytest.mark.integration, needs_db]

_ADAPTER_PATH = "app.api.trades.PaperTradeAdapter"


# ── GET /api/trades/balance ───────────────────────────────────────────────────

async def test_get_default_balance(client):
    with patch(_ADAPTER_PATH) as MockAdapter:
        instance = AsyncMock()
        instance.get_balance.return_value = 10_000.0
        MockAdapter.return_value = instance

        r = await client.get("/api/trades/balance")

    assert r.status_code == 200
    assert r.json() == {"balance": 10_000.0}


async def test_get_balance_zero(client):
    with patch(_ADAPTER_PATH) as MockAdapter:
        instance = AsyncMock()
        instance.get_balance.return_value = 0.0
        MockAdapter.return_value = instance

        r = await client.get("/api/trades/balance")

    assert r.status_code == 200
    assert r.json()["balance"] == 0.0


# ── GET /api/trades/balance/{config_id} ──────────────────────────────────────

async def test_get_all_balances_no_strategy(client):
    """When the strategy_id doesn't exist in DB, initial_assets defaults to {}."""
    with patch(_ADAPTER_PATH) as MockAdapter:
        instance = AsyncMock()
        instance.get_all_balances.return_value = {"USDT": 9_850.0, "BTC": 0.05}
        MockAdapter.return_value = instance

        r = await client.get("/api/trades/balance/nonexistent-strategy")

    assert r.status_code == 200
    data = r.json()
    assert "balances" in data
    assert data["balances"]["USDT"] == pytest.approx(9_850.0)
    assert data["balances"]["BTC"] == pytest.approx(0.05)


async def test_get_all_balances_with_strategy(client, db):
    """When strategy exists, initial_assets from params is passed to adapter."""
    from app.db.models.strategy_config import StrategyConfig

    strat = StrategyConfig(
        id="s1",
        name="Test",
        strategy_class="strategies.x.X",
        enabled=True,
        is_paper=True,
        params={"initial_assets": {"USDT": 5000.0}},
    )
    db.add(strat)
    await db.commit()

    with patch(_ADAPTER_PATH) as MockAdapter:
        instance = AsyncMock()
        instance.get_all_balances.return_value = {"USDT": 5000.0}
        MockAdapter.return_value = instance

        r = await client.get("/api/trades/balance/s1")

    assert r.status_code == 200
    # Adapter should have been constructed with config_id="s1" and initial_assets from params
    call_kwargs = MockAdapter.call_args
    assert call_kwargs.kwargs.get("config_id") == "s1" or call_kwargs.args[0] == "s1"


# ── GET /api/trades/position/{symbol} ────────────────────────────────────────

async def test_get_open_position_none(client):
    with patch(_ADAPTER_PATH) as MockAdapter:
        instance = AsyncMock()
        instance.get_open_position.return_value = None
        MockAdapter.return_value = instance

        r = await client.get("/api/trades/position/BTCUSDT")

    assert r.status_code == 200
    assert r.json() == {"open": False}


async def test_get_open_position_exists(client):
    from app.services.trade_adapter import PositionInfo

    mock_pos = PositionInfo(
        symbol="BTCUSDT", side="long", size=0.1,
        entry_price=50_000.0, unrealised_pnl=500.0, unrealised_pnl_pct=0.01,
    )
    with patch(_ADAPTER_PATH) as MockAdapter:
        instance = AsyncMock()
        instance.get_open_position.return_value = mock_pos
        MockAdapter.return_value = instance

        r = await client.get("/api/trades/position/BTCUSDT")

    assert r.status_code == 200
    data = r.json()
    assert data["open"] is True
    assert data["symbol"] == "BTCUSDT"
    assert data["side"] == "long"
    assert data["entry_price"] == pytest.approx(50_000.0)
