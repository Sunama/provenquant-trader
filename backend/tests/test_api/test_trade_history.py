"""
API tests for /api/trade-history endpoint.
Covers: list, filters (strategy_id, symbol), ordering, and fee field presence.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from app.db.models.strategy_config import StrategyConfig
from app.db.models.trade_history import TradeHistory
from tests.test_api.conftest import needs_db

pytestmark = [pytest.mark.integration, needs_db]


def _make_strategy(sid: str = "s1") -> StrategyConfig:
    return StrategyConfig(
        id=sid, name=f"Strategy {sid}", strategy_class="strategies.x.X",
        enabled=True, is_paper=True, params={},
    )


def _make_trade(
    strategy_id: str = "s1",
    symbol: str = "BTCUSDT",
    occurred_at: datetime | None = None,
    fee: float = 2.04,
) -> TradeHistory:
    if occurred_at is None:
        occurred_at = datetime.now(timezone.utc)
    return TradeHistory(
        strategy_id=strategy_id,
        occurred_at=occurred_at,
        trade_type="close_long",
        symbol=symbol,
        base_asset="BTC",
        quote_asset="USDT",
        bought_asset="USDT",
        sold_asset="BTC",
        bought_qty=5100.0,
        sold_qty=0.1,
        exchange_rate=51_000.0,
        fee=fee,
        fee_asset="USDT",
        exchange="paper",
        market_type="futures",
        leverage=1.0,
        reason="signal",
    )


# ── GET /api/trade-history/ ───────────────────────────────────────────────────

async def test_list_trade_history_empty(client):
    r = await client.get("/api/trade-history/")
    assert r.status_code == 200
    assert r.json() == []


async def test_list_trade_history_returns_records(client, db):
    strat = _make_strategy()
    db.add(strat)
    db.add(_make_trade())
    db.add(_make_trade(symbol="ETHUSDT"))
    await db.commit()

    r = await client.get("/api/trade-history/")
    assert r.status_code == 200
    assert len(r.json()) == 2


async def test_list_trade_history_default_limit_100(client, db):
    strat = _make_strategy()
    db.add(strat)
    now = datetime.now(timezone.utc)
    for i in range(120):
        db.add(_make_trade(occurred_at=now + timedelta(seconds=i)))
    await db.commit()

    r = await client.get("/api/trade-history/")
    assert r.status_code == 200
    assert len(r.json()) == 100


async def test_list_trade_history_custom_limit(client, db):
    strat = _make_strategy()
    db.add(strat)
    now = datetime.now(timezone.utc)
    for i in range(10):
        db.add(_make_trade(occurred_at=now + timedelta(seconds=i)))
    await db.commit()

    r = await client.get("/api/trade-history/?limit=5")
    assert r.status_code == 200
    assert len(r.json()) == 5


async def test_list_trade_history_ordered_by_occurred_at_desc(client, db):
    strat = _make_strategy()
    db.add(strat)
    base = datetime.now(timezone.utc)
    db.add(_make_trade(occurred_at=base))
    db.add(_make_trade(occurred_at=base + timedelta(seconds=60)))
    db.add(_make_trade(occurred_at=base + timedelta(seconds=30)))
    await db.commit()

    r = await client.get("/api/trade-history/")
    assert r.status_code == 200
    times = [row["occurred_at"] for row in r.json()]
    assert times == sorted(times, reverse=True)


async def test_filter_by_strategy_id(client, db):
    strat_a = _make_strategy("s-a")
    strat_b = _make_strategy("s-b")
    db.add(strat_a)
    db.add(strat_b)
    db.add(_make_trade(strategy_id="s-a"))
    db.add(_make_trade(strategy_id="s-b"))
    db.add(_make_trade(strategy_id="s-a"))
    await db.commit()

    r = await client.get("/api/trade-history/?strategy_id=s-a")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert all(row["strategy_id"] == "s-a" for row in data)


async def test_filter_by_symbol(client, db):
    strat = _make_strategy()
    db.add(strat)
    db.add(_make_trade(symbol="BTCUSDT"))
    db.add(_make_trade(symbol="ETHUSDT"))
    db.add(_make_trade(symbol="BTCUSDT"))
    await db.commit()

    r = await client.get("/api/trade-history/?symbol=BTCUSDT")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert all(row["symbol"] == "BTCUSDT" for row in data)


async def test_fee_and_fee_asset_present_in_response(client, db):
    """Response must include fee and fee_asset fields."""
    strat = _make_strategy()
    db.add(strat)
    db.add(_make_trade(fee=1.5))
    await db.commit()

    r = await client.get("/api/trade-history/")
    assert r.status_code == 200
    row = r.json()[0]
    assert "fee" in row
    assert "fee_asset" in row
    assert row["fee"] == pytest.approx(1.5)
    assert row["fee_asset"] == "USDT"


async def test_response_schema_fields(client, db):
    """Verify all expected fields are present in each response row."""
    strat = _make_strategy()
    db.add(strat)
    db.add(_make_trade())
    await db.commit()

    r = await client.get("/api/trade-history/")
    assert r.status_code == 200
    row = r.json()[0]
    expected_fields = {
        "id", "strategy_id", "occurred_at", "trade_type",
        "symbol", "base_asset", "quote_asset",
        "bought_asset", "sold_asset", "bought_qty", "sold_qty",
        "exchange_rate", "fee", "fee_asset",
        "exchange", "market_type", "leverage", "reason", "created_at",
    }
    assert expected_fields.issubset(set(row.keys()))
