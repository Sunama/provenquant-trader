"""
Unit tests for DataFetcher base class:
- emit callbacks fire for each data type
- subscriptions diff (add/remove) is computed correctly
- emit_orderbook writes to Redis but fires no callbacks
No WebSocket connections required.
"""
import json
import pytest
from unittest.mock import ANY, AsyncMock, call

from app.services.data_fetcher import (
    AggTradeData,
    DataFetcher,
    FundingRateData,
    LiquidationData,
    MarkPriceData,
    OpenInterestData,
    OrderBookData,
    Subscription,
    TickData,
)


# ── Minimal concrete DataFetcher for testing ──────────────────────────

class _StubFetcher(DataFetcher):
    async def _connect(self): pass
    async def _disconnect(self): pass
    async def _subscribe_symbols(self, subs): pass
    async def _unsubscribe_symbols(self, subs): pass


def _fetcher(mock_redis) -> _StubFetcher:
    f = _StubFetcher()
    f._redis = mock_redis
    return f


def _tick(close: float = 50_000.0) -> TickData:
    return TickData(
        asset_slug="btcusdt", timeframe="1m",
        time=1_700_000_000_000,
        open=close, high=close, low=close, close=close, volume=10.0,
    )


# ── _emit() tick ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_emit_stores_tick_in_redis(mock_redis):
    f = _fetcher(mock_redis)
    await f._emit(_tick())
    mock_redis.lpush.assert_called_once()


@pytest.mark.asyncio
async def test_emit_trims_redis_list(mock_redis):
    f = _fetcher(mock_redis)
    await f._emit(_tick())
    mock_redis.ltrim.assert_called_once()


@pytest.mark.asyncio
async def test_emit_publishes_to_broadcast_channel(mock_redis):
    f = _fetcher(mock_redis)
    await f._emit(_tick())
    mock_redis.publish.assert_called_once_with("ticks:broadcast", ANY)


@pytest.mark.asyncio
async def test_emit_invokes_all_tick_callbacks(mock_redis):
    f = _fetcher(mock_redis)
    cb1 = AsyncMock()
    cb2 = AsyncMock()
    f.add_callback(cb1)
    f.add_callback(cb2)
    tick = _tick(60_000.0)
    await f._emit(tick)
    cb1.assert_awaited_once_with(tick)
    cb2.assert_awaited_once_with(tick)


@pytest.mark.asyncio
async def test_emit_with_no_redis_does_not_crash():
    f = _StubFetcher()
    f._redis = None  # no Redis connection
    cb = AsyncMock()
    f.add_callback(cb)
    await f._emit(_tick())
    cb.assert_awaited_once()


@pytest.mark.asyncio
async def test_emit_uses_correct_redis_key(mock_redis):
    f = _fetcher(mock_redis)
    tick = TickData(asset_slug="ethusdt", timeframe="5m",
                    time=0, open=1, high=1, low=1, close=1, volume=1)
    await f._emit(tick)
    key = mock_redis.lpush.call_args.args[0]
    assert key == "tick:ethusdt:5m"


# ── _emit_funding_rate() ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_emit_funding_rate_stores_to_redis_set(mock_redis):
    f = _fetcher(mock_redis)
    data = FundingRateData(asset_slug="btcusdt", exchange="binance", time=0, rate=0.0001)
    await f._emit_funding_rate(data)
    mock_redis.set.assert_called_once()
    key = mock_redis.set.call_args.args[0]
    assert key == "funding:btcusdt:binance"


@pytest.mark.asyncio
async def test_emit_funding_rate_invokes_callbacks(mock_redis):
    f = _fetcher(mock_redis)
    cb = AsyncMock()
    f.add_funding_callback(cb)
    data = FundingRateData(asset_slug="btcusdt", exchange="binance", time=0, rate=0.0001)
    await f._emit_funding_rate(data)
    cb.assert_awaited_once_with(data)


# ── _emit_mark_price() ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_emit_mark_price_pushes_to_list(mock_redis):
    f = _fetcher(mock_redis)
    data = MarkPriceData(asset_slug="btcusdt", exchange="binance",
                         market_type="futures", time=0, price=50_000.0)
    await f._emit_mark_price(data)
    mock_redis.lpush.assert_called_once()


@pytest.mark.asyncio
async def test_emit_mark_price_uses_correct_key(mock_redis):
    f = _fetcher(mock_redis)
    data = MarkPriceData(asset_slug="btcusdt", exchange="binance",
                         market_type="futures", time=0, price=50_000.0)
    await f._emit_mark_price(data)
    key = mock_redis.lpush.call_args.args[0]
    assert key == "mark_price:btcusdt:binance:futures"


@pytest.mark.asyncio
async def test_emit_mark_price_invokes_callbacks(mock_redis):
    f = _fetcher(mock_redis)
    cb = AsyncMock()
    f.add_mark_price_callback(cb)
    data = MarkPriceData(asset_slug="btcusdt", exchange="binance",
                         market_type="futures", time=0, price=50_000.0)
    await f._emit_mark_price(data)
    cb.assert_awaited_once_with(data)


# ── _emit_liquidation() ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_emit_liquidation_uses_redis_stream(mock_redis):
    f = _fetcher(mock_redis)
    data = LiquidationData(asset_slug="btcusdt", exchange="binance",
                           time=0, side="long_liq", price=50_000.0, quantity=1.0)
    await f._emit_liquidation(data)
    mock_redis.xadd.assert_called_once()
    stream_key = mock_redis.xadd.call_args.args[0]
    assert stream_key == "liquidations:buffer"


@pytest.mark.asyncio
async def test_emit_liquidation_invokes_callbacks(mock_redis):
    f = _fetcher(mock_redis)
    cb = AsyncMock()
    f.add_liquidation_callback(cb)
    data = LiquidationData(asset_slug="btcusdt", exchange="binance",
                           time=0, side="long_liq", price=50_000.0, quantity=1.0)
    await f._emit_liquidation(data)
    cb.assert_awaited_once_with(data)


# ── _emit_agg_trade() ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_emit_agg_trade_uses_redis_stream(mock_redis):
    f = _fetcher(mock_redis)
    data = AggTradeData(asset_slug="btcusdt", exchange="binance",
                        time=0, price=50_000.0, quantity=0.01, is_buyer_maker=False)
    await f._emit_agg_trade(data)
    stream_key = mock_redis.xadd.call_args.args[0]
    assert stream_key == "agg_trades:buffer"


@pytest.mark.asyncio
async def test_emit_agg_trade_invokes_callbacks(mock_redis):
    f = _fetcher(mock_redis)
    cb = AsyncMock()
    f.add_agg_trade_callback(cb)
    data = AggTradeData(asset_slug="btcusdt", exchange="binance",
                        time=0, price=50_000.0, quantity=0.01, is_buyer_maker=True)
    await f._emit_agg_trade(data)
    cb.assert_awaited_once_with(data)


# ── _emit_orderbook() — Redis SET only, no callbacks ─────────────────

@pytest.mark.asyncio
async def test_emit_orderbook_writes_redis_set(mock_redis):
    f = _fetcher(mock_redis)
    data = OrderBookData(asset_slug="btcusdt", exchange="binance",
                         time=0, bids=[[50_000, 1]], asks=[[50_001, 1]])
    await f._emit_orderbook(data)
    mock_redis.set.assert_called_once()
    key = mock_redis.set.call_args.args[0]
    assert key == "orderbook:btcusdt:binance"


@pytest.mark.asyncio
async def test_emit_orderbook_no_callbacks_fired(mock_redis):
    """Order book has no callback mechanism — it's a snapshot only."""
    f = _fetcher(mock_redis)
    fired = []
    f.add_callback(AsyncMock(side_effect=lambda t: fired.append("tick")))
    f.add_funding_callback(AsyncMock(side_effect=lambda d: fired.append("funding")))
    data = OrderBookData(asset_slug="btcusdt", exchange="binance",
                         time=0, bids=[], asks=[])
    await f._emit_orderbook(data)
    assert fired == []


# ── Subscription management ───────────────────────────────────────────

def test_set_subscriptions_stores_by_key():
    f = _StubFetcher()
    subs = [
        Subscription("btcusdt", "1m", "binance", "futures"),
        Subscription("ethusdt", "5m", "binance", "spot"),
    ]
    f.set_subscriptions(subs)
    assert len(f._subscriptions) == 2


def test_set_subscriptions_deduplicates_same_slug_timeframe_market():
    f = _StubFetcher()
    subs = [
        Subscription("btcusdt", "1m", "binance", "futures"),
        Subscription("btcusdt", "1m", "binance", "futures"),  # duplicate
    ]
    f.set_subscriptions(subs)
    assert len(f._subscriptions) == 1


def test_set_subscriptions_replaces_previous():
    f = _StubFetcher()
    f.set_subscriptions([Subscription("btcusdt", "1m")])
    f.set_subscriptions([Subscription("ethusdt", "5m")])
    keys = list(f._subscriptions.keys())
    assert any("ethusdt" in k for k in keys)
    assert not any("btcusdt" in k for k in keys)
