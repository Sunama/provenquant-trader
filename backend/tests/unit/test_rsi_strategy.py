"""
Unit tests for RSIStrategy and its underlying _rsi() calculation.
No external services required — redis/db calls are mocked.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.data_fetcher import TickData
from app.services.strategy_executer import SignalAction, LegOrder, StrategyLeg
from strategies.example_rsi import RSIStrategy, _rsi


def _tick(close: float, symbol: str = "btcusdt") -> TickData:
    return TickData(
        symbol=symbol, timeframe="30m",
        time=1_700_000_000_000,
        open=close, high=close * 1.001, low=close * 0.999,
        close=close, volume=100.0,
    )


def _make_context(closes: list, status: str = "neutral", tick: TickData = None) -> MagicMock:
    """Build a mock StrategyContext with mocked redis fetcher."""
    if tick is None:
        tick = _tick(50_000.0)
    ctx = MagicMock()
    ctx.tick = tick
    ctx.leg_num = 0
    ctx.config_id = "cfg-test"
    ctx.redis = AsyncMock()
    ctx.redis.get_recent_closes = AsyncMock(return_value=closes)
    ctx.redis.get_status = AsyncMock(return_value=status)
    ctx.redis.set_status = AsyncMock()
    return ctx


# ── _rsi() pure function ──────────────────────────────────────────────

def test_rsi_insufficient_data_returns_50():
    assert _rsi([100.0, 101.0], period=14) == 50.0


def test_rsi_exactly_period_plus_one_values_is_sufficient():
    closes = list(range(100, 116))  # 16 values for period=14 (needs 15)
    assert _rsi(closes, period=14) != 50.0


def test_rsi_all_gains_returns_100():
    closes = list(range(100, 116))  # monotonically increasing
    assert _rsi(closes, period=14) == 100.0


def test_rsi_all_losses_returns_0():
    closes = list(range(115, 99, -1))  # monotonically decreasing
    assert _rsi(closes, period=14) == pytest.approx(0.0, abs=1e-9)


def test_rsi_equal_gains_and_losses_returns_50():
    closes = [100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100]
    assert _rsi(closes, period=14) == pytest.approx(50.0, abs=0.01)


def test_rsi_custom_period():
    closes = [100, 101, 100, 101, 100, 101]  # 6 values for period=5
    result = _rsi(closes, period=5)
    assert 0.0 <= result <= 100.0


# ── RSIStrategy class ─────────────────────────────────────────────────

def test_rsi_strategy_id_is_string():
    s = RSIStrategy()
    assert isinstance(s.id, str)
    assert s.id


def test_rsi_strategy_parameter_schema_has_six_entries():
    s = RSIStrategy()
    names = {p.name for p in s.parameter_schema}
    assert names == {"period", "oversold", "overbought", "amount", "tp_pct", "sl_pct"}


def test_rsi_strategy_parameter_schema_types():
    s = RSIStrategy()
    types = {p.name: p.type for p in s.parameter_schema}
    assert types["period"] == "int"
    assert types["oversold"] == "float"
    assert types["overbought"] == "float"
    assert types["amount"] == "float"


def test_rsi_strategy_default_subscription_uses_btcusdt():
    s = RSIStrategy()
    subs = s.subscriptions
    assert len(subs) == 1
    assert subs[0].symbol == "btcusdt"
    assert subs[0].tick_process is True


def test_rsi_strategy_uses_configured_legs():
    legs = [StrategyLeg(
        leg_num=0, role="primary", symbol="ethusdt",
        exchange="binance", market_type="futures", timeframe="1h", tick_process=True,
    )]
    s = RSIStrategy(legs=legs)
    subs = s.subscriptions
    assert subs[0].symbol == "ethusdt"
    assert subs[0].timeframe == "1h"


# ── RSIStrategy.execute() signal logic ───────────────────────────────

@pytest.mark.asyncio
async def test_execute_returns_none_with_insufficient_data():
    """Fewer than period+1 closes → _rsi returns 50.0 → no signal."""
    s = RSIStrategy(params={"period": 14, "oversold": 30.0, "overbought": 70.0, "amount": 0.5})
    ctx = _make_context(closes=[50_000.0], status="neutral")
    result = await s.execute(ctx)
    assert result is None


@pytest.mark.asyncio
async def test_execute_open_long_when_rsi_below_oversold():
    """All declining prices → RSI near 0 → ExecutionPlan with OPEN_LONG."""
    closes = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 94.0]
    tick = _tick(94.0)
    ctx = _make_context(closes=closes, status="neutral", tick=tick)
    s = RSIStrategy(params={"period": 5, "oversold": 30.0, "overbought": 70.0, "amount": 0.5})
    plan = await s.execute(ctx)
    assert plan is not None
    actions = {o.action for o in plan.orders}
    assert SignalAction.OPEN_LONG in actions


@pytest.mark.asyncio
async def test_execute_open_short_when_rsi_above_overbought():
    """All rising prices → RSI near 100 → ExecutionPlan with OPEN_SHORT."""
    closes = [90.0, 91.0, 92.0, 93.0, 94.0, 95.0, 96.0]
    tick = _tick(96.0)
    ctx = _make_context(closes=closes, status="neutral", tick=tick)
    s = RSIStrategy(params={"period": 5, "oversold": 30.0, "overbought": 70.0, "amount": 0.5})
    plan = await s.execute(ctx)
    assert plan is not None
    actions = {o.action for o in plan.orders}
    assert SignalAction.OPEN_SHORT in actions


@pytest.mark.asyncio
async def test_execute_no_signal_in_neutral_zone():
    """Alternating prices → RSI ≈ 50 → None returned."""
    closes = [100.0, 101.0, 100.0, 101.0, 100.0, 101.0, 100.0]
    ctx = _make_context(closes=closes, status="neutral", tick=_tick(100.0))
    s = RSIStrategy(params={"period": 5, "oversold": 30.0, "overbought": 70.0, "amount": 0.5})
    plan = await s.execute(ctx)
    assert plan is None


@pytest.mark.asyncio
async def test_execute_long_order_has_correct_amount():
    closes = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 94.0]
    ctx = _make_context(closes=closes, status="neutral", tick=_tick(94.0))
    s = RSIStrategy(params={"period": 5, "oversold": 30.0, "overbought": 70.0, "amount": 0.3})
    plan = await s.execute(ctx)
    assert plan is not None
    open_order = next(o for o in plan.orders if o.action == SignalAction.OPEN_LONG)
    assert open_order.amount == pytest.approx(0.3)


@pytest.mark.asyncio
async def test_execute_long_order_has_correct_tp_sl():
    closes = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 94.0]
    ctx = _make_context(closes=closes, status="neutral", tick=_tick(94.0))
    s = RSIStrategy(params={"period": 5, "oversold": 30.0, "overbought": 70.0,
                             "amount": 0.5, "tp_pct": 0.05, "sl_pct": 0.02})
    plan = await s.execute(ctx)
    assert plan is not None
    open_order = next(o for o in plan.orders if o.action == SignalAction.OPEN_LONG)
    assert open_order.tp_pct == pytest.approx(0.05)
    assert open_order.sl_pct == pytest.approx(0.02)


@pytest.mark.asyncio
async def test_execute_long_order_price_equals_tick_close():
    closes = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 94.0]
    tick = _tick(94.0)
    ctx = _make_context(closes=closes, status="neutral", tick=tick)
    s = RSIStrategy(params={"period": 5, "oversold": 30.0, "overbought": 70.0, "amount": 0.5})
    plan = await s.execute(ctx)
    assert plan is not None
    open_order = next(o for o in plan.orders if o.action == SignalAction.OPEN_LONG)
    assert open_order.price == pytest.approx(94.0)


@pytest.mark.asyncio
async def test_execute_no_repeat_long_if_already_long():
    """Status is already 'long' → no OPEN_LONG signal."""
    closes = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 94.0]
    ctx = _make_context(closes=closes, status="long", tick=_tick(94.0))
    s = RSIStrategy(params={"period": 5, "oversold": 30.0, "overbought": 70.0, "amount": 0.5})
    plan = await s.execute(ctx)
    if plan is not None:
        actions = {o.action for o in plan.orders}
        assert SignalAction.OPEN_LONG not in actions


@pytest.mark.asyncio
async def test_execute_sets_status_to_long_after_open_long():
    closes = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 94.0]
    ctx = _make_context(closes=closes, status="neutral", tick=_tick(94.0))
    s = RSIStrategy(params={"period": 5, "oversold": 30.0, "overbought": 70.0, "amount": 0.5})
    await s.execute(ctx)
    ctx.redis.set_status.assert_called_with("long")


@pytest.mark.asyncio
async def test_execute_sets_status_to_short_after_open_short():
    closes = [90.0, 91.0, 92.0, 93.0, 94.0, 95.0, 96.0]
    ctx = _make_context(closes=closes, status="neutral", tick=_tick(96.0))
    s = RSIStrategy(params={"period": 5, "oversold": 30.0, "overbought": 70.0, "amount": 0.5})
    await s.execute(ctx)
    ctx.redis.set_status.assert_called_with("short")


@pytest.mark.asyncio
async def test_execute_close_short_then_open_long_when_currently_short():
    """When status is 'short' and RSI is below oversold → CLOSE_SHORT then OPEN_LONG."""
    closes = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 94.0]
    ctx = _make_context(closes=closes, status="short", tick=_tick(94.0))
    s = RSIStrategy(params={"period": 5, "oversold": 30.0, "overbought": 70.0, "amount": 0.5})
    plan = await s.execute(ctx)
    assert plan is not None
    actions = [o.action for o in plan.orders]
    assert SignalAction.CLOSE_SHORT in actions
    assert SignalAction.OPEN_LONG in actions


@pytest.mark.asyncio
async def test_execute_close_long_then_open_short_when_currently_long():
    """When status is 'long' and RSI is above overbought → CLOSE_LONG then OPEN_SHORT."""
    closes = [90.0, 91.0, 92.0, 93.0, 94.0, 95.0, 96.0]
    ctx = _make_context(closes=closes, status="long", tick=_tick(96.0))
    s = RSIStrategy(params={"period": 5, "oversold": 30.0, "overbought": 70.0, "amount": 0.5})
    plan = await s.execute(ctx)
    assert plan is not None
    actions = [o.action for o in plan.orders]
    assert SignalAction.CLOSE_LONG in actions
    assert SignalAction.OPEN_SHORT in actions
