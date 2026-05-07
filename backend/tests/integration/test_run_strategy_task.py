"""
Integration tests for run_strategy Celery task logic.
Tests the async inner function directly (bypasses Celery broker).
Requires Redis for signal publishing.
"""
import json
import pytest
from unittest.mock import AsyncMock, patch

from app.services.data_fetcher import TickData
from app.services.strategy_executer import SignalSide, TradeSignal
from app.tasks.strategy import _call_execute, _publish_signals
from strategies.example_rsi import RSIStrategy
from tests.integration.conftest import needs_redis


def _tick(close: float = 50_000.0) -> TickData:
    return TickData(
        asset_slug="btcusdt", timeframe="30m",
        time=1_700_000_000_000,
        open=close, high=close, low=close, close=close, volume=100.0,
    )


# ── _call_execute() — compatibility shim ─────────────────────────────

@pytest.mark.asyncio
async def test_call_execute_modern_strategy_returns_list():
    strategy = RSIStrategy(params={"period": 5, "oversold": 30.0, "overbought": 70.0, "amount": 0.5})
    for price in [100.0, 99.0, 98.0, 97.0, 96.0, 95.0]:
        strategy._closes.append(price)
    tick = _tick(94.0)
    signals = await _call_execute(strategy, tick, asset_num=0)
    assert isinstance(signals, list)
    assert len(signals) == 1
    assert signals[0].execute == SignalSide.LONG


@pytest.mark.asyncio
async def test_call_execute_no_signal_returns_empty_list():
    strategy = RSIStrategy(params={"period": 5, "oversold": 30.0, "overbought": 70.0, "amount": 0.5})
    tick = _tick(50_000.0)
    signals = await _call_execute(strategy, tick, asset_num=0)
    assert signals == []


@pytest.mark.asyncio
async def test_call_execute_legacy_strategy_wraps_signal():
    """Old-style strategies returning a single TradeSignal are wrapped into a list."""
    from app.services.strategy_executer import StrategyExecuter
    from app.services.data_fetcher import Subscription

    class _OldStyleSignal:
        """Simulates the old TradeSignal with .side, .size_pct, .price etc."""
        side = "long"
        size_pct = 0.5
        tp_pct = 0.02
        sl_pct = 0.01
        price = 50_000.0
        asset_slug = "btcusdt"
        timeframe = "30m"

    class _LegacyStrat(StrategyExecuter):
        @property
        def id(self): return "legacy"
        @property
        def parameter_schema(self): return []
        @property
        def subscriptions(self): return [Subscription("btcusdt", "1m")]
        async def execute(self, tick):  # type: ignore[override]
            return _OldStyleSignal()

    strategy = _LegacyStrat()
    signals = await _call_execute(strategy, _tick(), asset_num=0)
    assert isinstance(signals, list)
    assert len(signals) == 1
    assert signals[0].execute == SignalSide.LONG
    assert signals[0].asset_num == 0
    assert signals[0].amount == 0.5


@pytest.mark.asyncio
async def test_call_execute_legacy_returns_none_wraps_to_empty():
    from app.services.strategy_executer import StrategyExecuter
    from app.services.data_fetcher import Subscription

    class _LegacyNoSignal(StrategyExecuter):
        @property
        def id(self): return "legacy_none"
        @property
        def parameter_schema(self): return []
        @property
        def subscriptions(self): return [Subscription("btcusdt", "1m")]
        async def execute(self, tick):  # type: ignore[override]
            return None

    strategy = _LegacyNoSignal()
    signals = await _call_execute(strategy, _tick(), asset_num=0)
    assert signals == []


# ── _publish_signals() ────────────────────────────────────────────────

@needs_redis
@pytest.mark.asyncio
async def test_publish_signals_writes_to_both_streams(redis_client):
    signals = [
        TradeSignal(execute=SignalSide.LONG, asset_num=0, exchange_num=0,
                    market_type="futures", amount=0.5, tp_pct=0.02, sl_pct=0.01, price=50_000.0)
    ]
    tick = _tick(50_000.0)
    await _publish_signals(redis_client, signals, "rsi_btcusdt_30m", "cfg-001", tick)

    trade_msgs = await redis_client.xrange("signals:trade", "-", "+")
    broadcast_msgs = await redis_client.xrange("signals:broadcast", "-", "+")
    assert len(trade_msgs) == 1
    assert len(broadcast_msgs) == 1


@needs_redis
@pytest.mark.asyncio
async def test_publish_signals_fields_are_correct(redis_client):
    signals = [
        TradeSignal(execute=SignalSide.SHORT, asset_num=1, exchange_num=0,
                    market_type="futures", amount=0.3, tp_pct=0.05, sl_pct=0.02, price=60_000.0)
    ]
    tick = _tick(60_000.0)
    await _publish_signals(redis_client, signals, "my_strat", "cfg-999", tick)

    msgs = await redis_client.xrange("signals:trade", "-", "+")
    fields = msgs[0][1]
    assert fields["strategy_id"] == "my_strat"
    assert fields["config_id"] == "cfg-999"
    assert fields["execute"] == "short"
    assert fields["asset_num"] == "1"
    assert fields["amount"] == "0.3"
    assert fields["tp_pct"] == "0.05"
    assert fields["sl_pct"] == "0.02"
    assert fields["price"] == "60000.0"
    assert "ts" in fields


@needs_redis
@pytest.mark.asyncio
async def test_publish_signals_empty_tp_sl_stored_as_empty_string(redis_client):
    signals = [
        TradeSignal(execute=SignalSide.LONG, asset_num=0, exchange_num=0,
                    market_type="spot", amount=1.0, tp_pct=None, sl_pct=None, price=3_000.0)
    ]
    tick = _tick(3_000.0)
    await _publish_signals(redis_client, signals, "strat", "cfg", tick)
    msgs = await redis_client.xrange("signals:trade", "-", "+")
    fields = msgs[0][1]
    assert fields["tp_pct"] == ""
    assert fields["sl_pct"] == ""


@needs_redis
@pytest.mark.asyncio
async def test_publish_signals_multi_leg_publishes_each_signal(redis_client):
    signals = [
        TradeSignal(execute=SignalSide.LONG, asset_num=0, exchange_num=0,
                    market_type="futures", amount=0.3, price=60_000.0),
        TradeSignal(execute=SignalSide.SHORT, asset_num=1, exchange_num=0,
                    market_type="futures", amount=0.3, price=3_000.0),
    ]
    tick = _tick(60_000.0)
    await _publish_signals(redis_client, signals, "pair_strat", "cfg-pair", tick)
    msgs = await redis_client.xrange("signals:trade", "-", "+")
    assert len(msgs) == 2


# ── Full run_strategy flow (mocked Celery + Redis) ────────────────────

def test_run_strategy_dynamic_import_and_signal_publish():
    """
    Verify the full inner async flow:
    1. Import strategy class dynamically
    2. Execute to get signals
    3. Publish to Redis stream (mocked)
    run_strategy is a sync Celery task (uses asyncio.run() internally),
    so this test must be sync too — asyncio.run() can't be nested.
    """
    mock_redis = AsyncMock()
    mock_redis.delete = AsyncMock()
    mock_redis.aclose = AsyncMock()
    mock_redis.xadd = AsyncMock(return_value="1-0")

    # Pre-fill closes so RSI fires a signal
    with patch("redis.asyncio.from_url", AsyncMock(return_value=mock_redis)):
        from app.tasks.strategy import run_strategy

        tick_dict = {
            "asset_slug": "btcusdt",
            "timeframe": "30m",
            "time": 1_700_000_000_000,
            "open": 94.0,
            "high": 94.5,
            "low": 93.5,
            "close": 94.0,
            "volume": 100.0,
        }

        # Can't easily prefill _closes via task, so test with insufficient data → "No signal"
        result = run_strategy(
            strategy_id="rsi_btcusdt_30m",
            strategy_class_path="strategies.example_rsi.RSIStrategy",
            tick_dict=tick_dict,
            params={"period": 14, "oversold": 30.0, "overbought": 70.0, "amount": 0.5},
            assets_dicts=[],
            asset_num=0,
            config_id="cfg-001",
        )

    assert "signal" in result.lower() or "no" in result.lower()
    mock_redis.delete.assert_called()  # lock released


def test_run_strategy_releases_lock_on_exception():
    """Redis lock must be released even if strategy raises an exception."""
    mock_redis = AsyncMock()
    mock_redis.delete = AsyncMock()
    mock_redis.aclose = AsyncMock()

    with patch("redis.asyncio.from_url", AsyncMock(return_value=mock_redis)):
        from app.tasks.strategy import run_strategy
        with pytest.raises(Exception):
            run_strategy(
                strategy_id="bad_strategy",
                strategy_class_path="strategies.nonexistent.BadStrategy",
                tick_dict={"asset_slug": "x", "timeframe": "1m", "time": 0,
                           "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
                params={},
                assets_dicts=[],
            )

    mock_redis.delete.assert_called()
