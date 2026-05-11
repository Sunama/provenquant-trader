"""
Unit tests for PairTradeStrategy (multi-leg BTC/ETH mean reversion).
context.db is mocked — no DB required.
"""
import pytest
import numpy as np
from unittest.mock import AsyncMock, MagicMock

from app.services.data_fetcher import TickData
from app.services.strategy_executer import SignalAction
from strategies.example_pair_trade import PairTradeStrategy


def _tick(close: float, symbol: str = "btcusdt") -> TickData:
    return TickData(
        symbol=symbol, timeframe="1h",
        time=1_700_000_000_000,
        open=close, high=close * 1.001, low=close * 0.999,
        close=close, volume=100.0,
    )


def _klines(prices: list):
    """Build fake kline objects with a .close attribute."""
    class _K:
        def __init__(self, c): self.close = c
    return [_K(p) for p in prices]


def _make_context(btc_closes: list, eth_closes: list, leg_num: int = 0) -> MagicMock:
    """Build a mock StrategyContext with mocked db fetcher."""
    tick = _tick(btc_closes[-1] if btc_closes else 60_000.0)
    ctx = MagicMock()
    ctx.tick = tick
    ctx.leg_num = leg_num
    ctx.config_id = "cfg-test"
    ctx.db = AsyncMock()
    ctx.db.get_klines = AsyncMock(side_effect=[
        _klines(btc_closes),
        _klines(eth_closes),
    ])
    return ctx


# ── Static checks ─────────────────────────────────────────────────────

def test_pair_trade_id_is_string():
    assert isinstance(PairTradeStrategy().id, str)


def test_pair_trade_parameter_schema_names():
    names = {p.name for p in PairTradeStrategy().parameter_schema}
    assert names == {"lookback", "z_threshold", "amount"}


def test_pair_trade_subscriptions():
    subs = PairTradeStrategy().subscriptions
    symbols = [s.symbol for s in subs]
    assert "btcusdt" in symbols
    assert "ethusdt" in symbols
    assert len(subs) == 2


def test_pair_trade_btc_is_trigger_asset():
    subs = PairTradeStrategy().subscriptions
    btc_sub = next(s for s in subs if s.symbol == "btcusdt")
    assert btc_sub.tick_process is True


def test_pair_trade_eth_is_not_trigger():
    subs = PairTradeStrategy().subscriptions
    eth_sub = next(s for s in subs if s.symbol == "ethusdt")
    assert eth_sub.tick_process is False


# ── execute() routing ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_skips_non_primary_leg():
    """leg_num != 0 should return None without querying DB."""
    s = PairTradeStrategy()
    ctx = MagicMock()
    ctx.leg_num = 1
    result = await s.execute(ctx)
    assert result is None


# ── Insufficient data ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_returns_none_when_klines_too_short():
    s = PairTradeStrategy(params={"lookback": 20, "z_threshold": 2.0, "amount": 0.3})
    ctx = _make_context(
        btc_closes=[60_000.0] * 10,  # < lookback=20
        eth_closes=[2_000.0] * 10,
    )
    result = await s.execute(ctx)
    assert result is None


@pytest.mark.asyncio
async def test_execute_returns_none_when_ratio_std_is_zero():
    """Constant ratio → std=0 → guard triggers → None."""
    lookback = 5
    s = PairTradeStrategy(params={"lookback": lookback, "z_threshold": 2.0, "amount": 0.3})
    btc = [60_000.0] * (lookback + 5)
    eth = [2_000.0] * (lookback + 5)
    ctx = _make_context(btc_closes=btc, eth_closes=eth)
    result = await s.execute(ctx)
    assert result is None


# ── Signal direction ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_long_btc_short_eth_when_ratio_is_very_low():
    """
    BTC cheap relative to ETH → z << -threshold → OPEN_LONG leg 0 + OPEN_SHORT leg 1.

    BTC alternates 59k/61k → ratio mean≈30, std≈0.5.
    tick.close = 40000 → current_ratio = 20 → z ≈ -20.
    """
    lookback = 5
    s = PairTradeStrategy(params={"lookback": lookback, "z_threshold": 2.0, "amount": 0.3})
    btc = [59_000, 61_000, 59_000, 61_000, 59_000, 61_000, 59_000, 61_000, 59_000, 61_000]
    eth = [2_000.0] * 10
    ctx = _make_context(btc_closes=btc, eth_closes=eth)
    ctx.tick = _tick(40_000.0)

    plan = await s.execute(ctx)
    assert plan is not None
    actions_by_leg = {o.leg_num: o.action for o in plan.orders}
    assert actions_by_leg[0] == SignalAction.OPEN_LONG   # long BTC
    assert actions_by_leg[1] == SignalAction.OPEN_SHORT  # short ETH


@pytest.mark.asyncio
async def test_execute_short_btc_long_eth_when_ratio_is_very_high():
    """BTC expensive relative to ETH → z >> threshold → OPEN_SHORT leg 0 + OPEN_LONG leg 1."""
    lookback = 5
    s = PairTradeStrategy(params={"lookback": lookback, "z_threshold": 2.0, "amount": 0.3})
    btc = [59_000, 61_000, 59_000, 61_000, 59_000, 61_000, 59_000, 61_000, 59_000, 61_000]
    eth = [2_000.0] * 10
    ctx = _make_context(btc_closes=btc, eth_closes=eth)
    ctx.tick = _tick(80_000.0)  # ratio = 40 → z ≈ +20

    plan = await s.execute(ctx)
    assert plan is not None
    actions_by_leg = {o.leg_num: o.action for o in plan.orders}
    assert actions_by_leg[0] == SignalAction.OPEN_SHORT  # short BTC
    assert actions_by_leg[1] == SignalAction.OPEN_LONG   # long ETH


@pytest.mark.asyncio
async def test_execute_no_signal_in_neutral_zone():
    """Current ratio ≈ mean → |z| < threshold → None."""
    lookback = 5
    s = PairTradeStrategy(params={"lookback": lookback, "z_threshold": 2.0, "amount": 0.3})
    btc = [59_000, 61_000, 59_000, 61_000, 59_000, 61_000, 59_000, 61_000, 59_000, 61_000]
    eth = [2_000.0] * 10
    ctx = _make_context(btc_closes=btc, eth_closes=eth)
    ctx.tick = _tick(60_000.0)  # ratio = 30 = mean → z = 0

    plan = await s.execute(ctx)
    assert plan is None


@pytest.mark.asyncio
async def test_execute_signal_uses_configured_amount():
    lookback = 5
    s = PairTradeStrategy(params={"lookback": lookback, "z_threshold": 2.0, "amount": 0.25})
    btc = [59_000, 61_000, 59_000, 61_000, 59_000, 61_000, 59_000, 61_000, 59_000, 61_000]
    eth = [2_000.0] * 10
    ctx = _make_context(btc_closes=btc, eth_closes=eth)
    ctx.tick = _tick(40_000.0)

    plan = await s.execute(ctx)
    assert plan is not None
    for order in plan.orders:
        assert order.amount == pytest.approx(0.25)


@pytest.mark.asyncio
async def test_execute_always_returns_two_leg_orders():
    """A valid signal always produces exactly 2 orders (one per leg)."""
    lookback = 5
    s = PairTradeStrategy(params={"lookback": lookback, "z_threshold": 2.0, "amount": 0.3})
    btc = [59_000, 61_000, 59_000, 61_000, 59_000, 61_000, 59_000, 61_000, 59_000, 61_000]
    eth = [2_000.0] * 10
    ctx = _make_context(btc_closes=btc, eth_closes=eth)
    ctx.tick = _tick(40_000.0)

    plan = await s.execute(ctx)
    assert plan is not None
    assert len(plan.orders) == 2
