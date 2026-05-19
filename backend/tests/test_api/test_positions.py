"""
API tests for /api/positions endpoints.
Covers: list, get, stats, and manual close (including fee deduction).
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models.position import Position
from app.db.models.strategy_asset import StrategyAsset
from app.db.models.strategy_config import StrategyConfig
from app.db.models.trade_history import TradeHistory
from app.services.trade_adapter import OrderResult
from tests.test_api.conftest import needs_db

pytestmark = [pytest.mark.integration, needs_db]


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_strategy(strategy_id: str = "strat-1") -> StrategyConfig:
    return StrategyConfig(
        id=strategy_id,
        name="Test Strategy",
        strategy_class="strategies.example.MyStrategy",
        enabled=True,
        is_paper=True,
        params={},
    )


def _make_asset(strategy_id: str = "strat-1") -> StrategyAsset:
    return StrategyAsset(
        strategy_id=strategy_id,
        leg_num=0,
        role="primary",
        symbol="BTCUSDT",
        exchange="binance",
        timeframe="30m",
        market_type="futures",
        base_asset="BTC",
        quote_asset="USDT",
        transaction_fee=0.0004,
        leverage=1.0,
    )


def _make_open_position(strategy_id: str = "strat-1") -> Position:
    return Position(
        strategy_id=strategy_id,
        symbol="BTCUSDT",
        side="long",
        entry_price=50_000.0,
        entry_time=datetime.now(timezone.utc),
        size=0.1,
        market_type="futures",
        leverage=1.0,
        is_open=True,
    )


def _make_closed_position(strategy_id: str = "strat-1", pnl: float = 100.0) -> Position:
    return Position(
        strategy_id=strategy_id,
        symbol="BTCUSDT",
        side="long",
        entry_price=50_000.0,
        entry_time=datetime.now(timezone.utc),
        size=0.1,
        market_type="futures",
        leverage=1.0,
        is_open=False,
        exit_price=51_000.0,
        exit_time=datetime.now(timezone.utc),
        exit_reason="signal",
        pnl=pnl,
        pnl_pct=pnl / (50_000.0 * 0.1),
    )


# ── GET /api/positions/ ───────────────────────────────────────────────────────

async def test_list_positions_empty(client):
    r = await client.get("/api/positions/")
    assert r.status_code == 200
    assert r.json() == []


async def test_list_positions_returns_all(client, db):
    strat = _make_strategy()
    pos = _make_open_position()
    db.add(strat)
    db.add(pos)
    await db.commit()

    r = await client.get("/api/positions/")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["symbol"] == "BTCUSDT"
    assert data[0]["is_open"] is True


async def test_list_positions_open_only_filter(client, db):
    strat = _make_strategy()
    db.add(strat)
    db.add(_make_open_position())
    db.add(_make_closed_position())
    await db.commit()

    r = await client.get("/api/positions/?open_only=true")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["is_open"] is True


async def test_list_positions_by_strategy_id(client, db):
    strat_a = _make_strategy("strat-a")
    strat_b = _make_strategy("strat-b")
    db.add(strat_a)
    db.add(strat_b)
    db.add(_make_open_position("strat-a"))
    db.add(_make_open_position("strat-b"))
    await db.commit()

    r = await client.get("/api/positions/?strategy_id=strat-a")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["strategy_id"] == "strat-a"


async def test_list_positions_limit(client, db):
    strat = _make_strategy()
    db.add(strat)
    for _ in range(5):
        db.add(_make_closed_position())
    await db.commit()

    r = await client.get("/api/positions/?limit=3")
    assert r.status_code == 200
    assert len(r.json()) == 3


# ── GET /api/positions/{id} ───────────────────────────────────────────────────

async def test_get_position_not_found(client):
    r = await client.get("/api/positions/999")
    assert r.status_code == 404


async def test_get_position(client, db):
    strat = _make_strategy()
    pos = _make_open_position()
    db.add(strat)
    db.add(pos)
    await db.commit()
    await db.refresh(pos)

    r = await client.get(f"/api/positions/{pos.id}")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == pos.id
    assert data["symbol"] == "BTCUSDT"
    assert data["side"] == "long"
    assert data["entry_price"] == 50_000.0
    assert data["is_open"] is True


# ── GET /api/positions/stats ─────────────────────────────────────────────────

async def test_stats_empty(client):
    r = await client.get("/api/positions/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["total_trades"] == 0
    assert data["total_pnl"] == 0.0
    assert data["win_rate"] == 0.0
    assert data["wins"] == 0


async def test_stats_with_closed_positions(client, db):
    strat = _make_strategy()
    db.add(strat)
    db.add(_make_closed_position(pnl=200.0))   # win
    db.add(_make_closed_position(pnl=-50.0))   # loss
    db.add(_make_closed_position(pnl=100.0))   # win
    await db.commit()

    r = await client.get("/api/positions/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["total_trades"] == 3
    assert data["total_pnl"] == pytest.approx(250.0)
    assert data["wins"] == 2
    assert data["win_rate"] == pytest.approx(2 / 3, rel=1e-3)


async def test_stats_filtered_by_strategy(client, db):
    strat_a = _make_strategy("strat-a")
    strat_b = _make_strategy("strat-b")
    db.add(strat_a)
    db.add(strat_b)
    db.add(_make_closed_position("strat-a", pnl=100.0))
    db.add(_make_closed_position("strat-b", pnl=-50.0))
    await db.commit()

    r = await client.get("/api/positions/stats?strategy_id=strat-a")
    assert r.status_code == 200
    data = r.json()
    assert data["total_trades"] == 1
    assert data["total_pnl"] == pytest.approx(100.0)


# ── POST /api/positions/{id}/close ────────────────────────────────────────────

async def test_close_position_not_found(client):
    r = await client.post("/api/positions/999/close", json={"price": 51000.0})
    assert r.status_code == 404


async def test_close_already_closed_position(client, db):
    strat = _make_strategy()
    closed = _make_closed_position()
    db.add(strat)
    db.add(closed)
    await db.commit()
    await db.refresh(closed)

    r = await client.post(f"/api/positions/{closed.id}/close", json={"price": 51000.0})
    assert r.status_code == 404


async def test_close_position_long_pnl_net_of_fee(client, db):
    """Long close: pnl = (exit - entry) * size - fee, fee = close_cost * transaction_fee."""
    strat = _make_strategy()
    asset = _make_asset()  # transaction_fee = 0.0004
    pos = _make_open_position()
    db.add(strat)
    db.add(asset)
    db.add(pos)
    await db.commit()
    await db.refresh(pos)

    exit_price = 51_000.0
    gross_pnl = (exit_price - 50_000.0) * 0.1  # 100.0
    close_cost = exit_price * 0.1               # 5100.0
    fee = close_cost * 0.0004                   # 2.04
    expected_pnl = gross_pnl - fee              # 97.96

    mock_result = OrderResult(
        order_id="order-1", symbol="BTCUSDT", side="long",
        price=exit_price, size=0.1, status="filled",
    )
    with patch("app.api.positions.PaperTradeAdapter") as MockAdapter:
        instance = AsyncMock()
        instance.close_position.return_value = mock_result
        MockAdapter.return_value = instance

        r = await client.post(f"/api/positions/{pos.id}/close", json={"price": exit_price})

    assert r.status_code == 200
    data = r.json()
    assert data["is_open"] is False
    assert data["exit_price"] == pytest.approx(exit_price)
    assert data["exit_reason"] == "Manual Close Position"
    assert data["pnl"] == pytest.approx(expected_pnl, rel=1e-6)


async def test_close_position_short_pnl_net_of_fee(client, db):
    """Short close: pnl = (entry - exit) * size - fee."""
    strat = _make_strategy()
    asset = _make_asset()
    pos = Position(
        strategy_id="strat-1",
        symbol="BTCUSDT",
        side="short",
        entry_price=50_000.0,
        entry_time=datetime.now(timezone.utc),
        size=0.1,
        market_type="futures",
        leverage=1.0,
        is_open=True,
    )
    db.add(strat)
    db.add(asset)
    db.add(pos)
    await db.commit()
    await db.refresh(pos)

    exit_price = 49_000.0
    gross_pnl = (50_000.0 - exit_price) * 0.1  # 100.0
    close_cost = exit_price * 0.1               # 4900.0
    fee = close_cost * 0.0004                   # 1.96
    expected_pnl = gross_pnl - fee              # 98.04

    mock_result = OrderResult(
        order_id="order-2", symbol="BTCUSDT", side="short",
        price=exit_price, size=0.1, status="filled",
    )
    with patch("app.api.positions.PaperTradeAdapter") as MockAdapter:
        instance = AsyncMock()
        instance.close_position.return_value = mock_result
        MockAdapter.return_value = instance

        r = await client.post(f"/api/positions/{pos.id}/close", json={"price": exit_price})

    assert r.status_code == 200
    data = r.json()
    assert data["pnl"] == pytest.approx(expected_pnl, rel=1e-6)


async def test_close_position_fee_recorded_in_trade_history(client, db):
    """TradeHistory entry must carry the computed fee, not 0."""
    from sqlalchemy.future import select as fsel
    strat = _make_strategy()
    asset = _make_asset()  # transaction_fee = 0.0004
    pos = _make_open_position()
    db.add(strat)
    db.add(asset)
    db.add(pos)
    await db.commit()
    await db.refresh(pos)

    exit_price = 51_000.0
    expected_fee = exit_price * 0.1 * 0.0004  # 2.04

    mock_result = OrderResult(
        order_id="order-3", symbol="BTCUSDT", side="long",
        price=exit_price, size=0.1, status="filled",
    )
    with patch("app.api.positions.PaperTradeAdapter") as MockAdapter:
        instance = AsyncMock()
        instance.close_position.return_value = mock_result
        MockAdapter.return_value = instance
        await client.post(f"/api/positions/{pos.id}/close", json={"price": exit_price})

    async with db.begin_nested():
        rows = (await db.execute(fsel(TradeHistory))).scalars().all()
    assert len(rows) == 1
    assert rows[0].fee == pytest.approx(expected_fee, rel=1e-6)
    assert rows[0].fee_asset == "USDT"


async def test_close_position_no_asset_falls_back_to_zero_fee(client, db):
    """When no StrategyAsset exists, fee defaults to 0 (no crash)."""
    strat = _make_strategy()
    pos = _make_open_position()  # no asset inserted
    db.add(strat)
    db.add(pos)
    await db.commit()
    await db.refresh(pos)

    exit_price = 51_000.0
    gross_pnl = (exit_price - 50_000.0) * 0.1  # 100.0

    mock_result = OrderResult(
        order_id="order-4", symbol="BTCUSDT", side="long",
        price=exit_price, size=0.1, status="filled",
    )
    with patch("app.api.positions.PaperTradeAdapter") as MockAdapter:
        instance = AsyncMock()
        instance.close_position.return_value = mock_result
        MockAdapter.return_value = instance

        r = await client.post(f"/api/positions/{pos.id}/close", json={"price": exit_price})

    assert r.status_code == 200
    assert r.json()["pnl"] == pytest.approx(gross_pnl)


# ── auth guard ────────────────────────────────────────────────────────────────

async def test_unauthorized_returns_401(client):
    from httpx import AsyncClient, ASGITransport
    from main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as unauth:
        r = await unauth.get("/api/positions/")
    assert r.status_code == 401
