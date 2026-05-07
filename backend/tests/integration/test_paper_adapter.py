"""
Integration tests for PaperTradeAdapter.
Requires a running Redis instance (skipped otherwise).
Uses DB 15 for isolation.
"""
import pytest
from unittest.mock import patch, AsyncMock

from app.services.trade_adapter.paper import PaperTradeAdapter
from tests.integration.conftest import needs_redis


# ── Helpers ───────────────────────────────────────────────────────────

def _adapter(redis_client, balance: float = 10_000.0) -> PaperTradeAdapter:
    adapter = PaperTradeAdapter(initial_balance=balance)
    adapter._redis = redis_client  # inject test Redis
    return adapter


# ── get_balance() ─────────────────────────────────────────────────────

@needs_redis
@pytest.mark.asyncio
async def test_get_balance_returns_default_on_first_call(redis_client):
    adapter = _adapter(redis_client, balance=10_000.0)
    balance = await adapter.get_balance()
    assert balance == pytest.approx(10_000.0)


@needs_redis
@pytest.mark.asyncio
async def test_get_balance_initialises_redis_key(redis_client):
    adapter = _adapter(redis_client, balance=5_000.0)
    await adapter.get_balance()
    raw = await redis_client.get("paper:balance")
    assert float(raw) == pytest.approx(5_000.0)


@needs_redis
@pytest.mark.asyncio
async def test_get_balance_reads_existing_key(redis_client):
    await redis_client.set("paper:balance", "7500.0")
    adapter = _adapter(redis_client)
    balance = await adapter.get_balance()
    assert balance == pytest.approx(7_500.0)


# ── open_position() ───────────────────────────────────────────────────

@needs_redis
@pytest.mark.asyncio
async def test_open_position_deducts_cost_from_balance(redis_client):
    adapter = _adapter(redis_client, balance=10_000.0)
    await adapter.get_balance()  # initialise key
    price = 50_000.0
    size = 0.1  # cost = 5000
    await adapter.open_position("btcusdt", "long", size, price)
    balance_after = await adapter.get_balance()
    assert balance_after == pytest.approx(10_000.0 - price * size)


@needs_redis
@pytest.mark.asyncio
async def test_open_position_stores_position_in_redis(redis_client):
    adapter = _adapter(redis_client, balance=10_000.0)
    await adapter.get_balance()
    await adapter.open_position("btcusdt", "long", 0.1, 50_000.0, tp_price=51_000.0, sl_price=49_000.0)
    import json
    raw = await redis_client.get("paper:position:btcusdt")
    pos = json.loads(raw)
    assert pos["asset_slug"] == "btcusdt"
    assert pos["side"] == "long"
    assert pos["size"] == pytest.approx(0.1)
    assert pos["entry_price"] == pytest.approx(50_000.0)
    assert pos["tp_price"] == pytest.approx(51_000.0)
    assert pos["sl_price"] == pytest.approx(49_000.0)


@needs_redis
@pytest.mark.asyncio
async def test_open_position_returns_order_result(redis_client):
    adapter = _adapter(redis_client, balance=10_000.0)
    await adapter.get_balance()
    result = await adapter.open_position("btcusdt", "long", 0.1, 50_000.0)
    assert result.asset_slug == "btcusdt"
    assert result.side == "long"
    assert result.price == pytest.approx(50_000.0)
    assert result.size == pytest.approx(0.1)
    assert result.status == "filled"


@needs_redis
@pytest.mark.asyncio
async def test_open_position_raises_on_insufficient_balance(redis_client):
    adapter = _adapter(redis_client, balance=100.0)
    await adapter.get_balance()
    with pytest.raises(ValueError, match="Insufficient"):
        await adapter.open_position("btcusdt", "long", 0.1, 50_000.0)  # cost = 5000 > 100


# ── get_open_position() ───────────────────────────────────────────────

@needs_redis
@pytest.mark.asyncio
async def test_get_open_position_returns_none_when_no_position(redis_client):
    adapter = _adapter(redis_client)
    pos = await adapter.get_open_position("btcusdt")
    assert pos is None


@needs_redis
@pytest.mark.asyncio
async def test_get_open_position_returns_position_info(redis_client):
    adapter = _adapter(redis_client, balance=10_000.0)
    await adapter.get_balance()
    await adapter.open_position("btcusdt", "long", 0.1, 50_000.0)
    pos = await adapter.get_open_position("btcusdt")
    assert pos is not None
    assert pos.asset_slug == "btcusdt"
    assert pos.side == "long"
    assert pos.size == pytest.approx(0.1)
    assert pos.entry_price == pytest.approx(50_000.0)


# ── close_position() ─────────────────────────────────────────────────

@needs_redis
@pytest.mark.asyncio
async def test_close_long_position_at_profit_increases_balance(redis_client):
    adapter = _adapter(redis_client, balance=10_000.0)
    await adapter.get_balance()
    entry = 50_000.0
    size = 0.1
    await adapter.open_position("btcusdt", "long", size, entry)
    balance_after_open = await adapter.get_balance()

    exit_price = 55_000.0
    await adapter.close_position("btcusdt", "long", exit_price)
    balance_final = await adapter.get_balance()

    pnl = (exit_price - entry) * size  # = 500
    assert balance_final == pytest.approx(balance_after_open + exit_price * size + pnl)


@needs_redis
@pytest.mark.asyncio
async def test_close_short_position_at_profit_increases_balance(redis_client):
    adapter = _adapter(redis_client, balance=10_000.0)
    await adapter.get_balance()
    entry = 55_000.0
    size = 0.1
    await adapter.open_position("btcusdt", "short", size, entry)
    balance_after_open = await adapter.get_balance()

    exit_price = 50_000.0  # price went down → short is profitable
    await adapter.close_position("btcusdt", "short", exit_price)
    balance_final = await adapter.get_balance()

    pnl = (entry - exit_price) * size  # = 500
    assert balance_final == pytest.approx(balance_after_open + exit_price * size + pnl)


@needs_redis
@pytest.mark.asyncio
async def test_close_position_removes_from_redis(redis_client):
    adapter = _adapter(redis_client, balance=10_000.0)
    await adapter.get_balance()
    await adapter.open_position("btcusdt", "long", 0.1, 50_000.0)
    await adapter.close_position("btcusdt", "long", 51_000.0)
    pos = await adapter.get_open_position("btcusdt")
    assert pos is None


@needs_redis
@pytest.mark.asyncio
async def test_close_position_raises_when_no_open_position(redis_client):
    adapter = _adapter(redis_client)
    with pytest.raises(ValueError, match="No open position"):
        await adapter.close_position("btcusdt", "long", 50_000.0)


@needs_redis
@pytest.mark.asyncio
async def test_close_position_returns_order_result(redis_client):
    adapter = _adapter(redis_client, balance=10_000.0)
    await adapter.get_balance()
    await adapter.open_position("btcusdt", "long", 0.1, 50_000.0)
    result = await adapter.close_position("btcusdt", "long", 51_000.0)
    assert result.price == pytest.approx(51_000.0)
    assert result.status == "filled"


# ── End-to-end flow ───────────────────────────────────────────────────

@needs_redis
@pytest.mark.asyncio
async def test_full_long_trade_round_trip(redis_client):
    """Open LONG, close at profit — balance should net increase."""
    adapter = _adapter(redis_client, balance=10_000.0)
    initial_balance = await adapter.get_balance()

    entry, exit_price, size = 50_000.0, 55_000.0, 0.1
    await adapter.open_position("btcusdt", "long", size, entry)
    await adapter.close_position("btcusdt", "long", exit_price)

    final_balance = await adapter.get_balance()
    expected_pnl = (exit_price - entry) * size  # 500.0
    assert final_balance == pytest.approx(initial_balance + expected_pnl)


@needs_redis
@pytest.mark.asyncio
async def test_full_short_trade_at_loss_reduces_balance(redis_client):
    """Open SHORT, close at a loss — balance should decrease."""
    adapter = _adapter(redis_client, balance=10_000.0)
    initial_balance = await adapter.get_balance()

    entry, exit_price, size = 50_000.0, 52_000.0, 0.1
    await adapter.open_position("btcusdt", "short", size, entry)
    await adapter.close_position("btcusdt", "short", exit_price)

    final_balance = await adapter.get_balance()
    expected_pnl = (entry - exit_price) * size  # -200.0
    assert final_balance == pytest.approx(initial_balance + expected_pnl)
