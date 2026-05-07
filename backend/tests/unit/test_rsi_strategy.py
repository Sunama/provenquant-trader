"""
Unit tests for RSIStrategy and its underlying _rsi() calculation.
No external services required.
"""
import pytest
from app.services.data_fetcher import TickData
from app.services.strategy_executer import SignalSide, StrategyAssetConfig
from strategies.example_rsi import RSIStrategy, _rsi


def _tick(close: float, asset_slug: str = "btcusdt") -> TickData:
    return TickData(
        asset_slug=asset_slug, timeframe="30m",
        time=1_700_000_000_000,
        open=close, high=close * 1.001, low=close * 0.999,
        close=close, volume=100.0,
    )


# ── _rsi() pure function ──────────────────────────────────────────────

def test_rsi_insufficient_data_returns_50():
    assert _rsi([100.0, 101.0], period=14) == 50.0


def test_rsi_exactly_period_plus_one_values_is_sufficient():
    closes = list(range(100, 116))  # 16 values for period=14 (needs 15)
    result = _rsi(closes, period=14)
    assert result != 50.0  # should produce a real value


def test_rsi_all_gains_returns_100():
    closes = list(range(100, 116))  # monotonically increasing
    assert _rsi(closes, period=14) == 100.0


def test_rsi_all_losses_returns_0():
    closes = list(range(115, 99, -1))  # monotonically decreasing
    assert _rsi(closes, period=14) == pytest.approx(0.0, abs=1e-9)


def test_rsi_equal_gains_and_losses_returns_50():
    # Alternating: each up-move = each down-move (balanced gains/losses)
    closes = [100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100]
    result = _rsi(closes, period=14)
    assert result == pytest.approx(50.0, abs=0.01)


def test_rsi_uses_only_last_period_plus_one_values():
    """Prepend 100 noise values; only last 15 (period+1) should drive RSI."""
    noise = [999.0] * 100
    signal_part = list(range(100, 116))  # all gains → RSI 100
    closes = noise + signal_part
    assert _rsi(closes, period=14) == 100.0


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
    schema = s.parameter_schema
    names = {p.name for p in schema}
    assert names == {"period", "oversold", "overbought", "amount", "tp_pct", "sl_pct"}


def test_rsi_strategy_parameter_schema_types():
    s = RSIStrategy()
    types = {p.name: p.type for p in s.parameter_schema}
    assert types["period"] == "int"
    assert types["oversold"] == "float"
    assert types["overbought"] == "float"
    assert types["amount"] == "float"


def test_rsi_strategy_is_not_legacy():
    assert RSIStrategy._is_legacy() is False


def test_rsi_strategy_default_subscriptions_use_btcusdt():
    s = RSIStrategy()
    subs = s.subscriptions
    assert len(subs) == 1
    assert subs[0].asset_slug == "btcusdt"
    assert subs[0].tick_process is True


def test_rsi_strategy_uses_configured_assets():
    assets = [StrategyAssetConfig(0, "ethusdt", "binance", "1h", "futures", True)]
    s = RSIStrategy(assets=assets)
    subs = s.subscriptions
    assert subs[0].asset_slug == "ethusdt"
    assert subs[0].timeframe == "1h"


# ── RSIStrategy.execute() signal logic ────────────────────────────────

@pytest.mark.asyncio
async def test_execute_returns_empty_with_insufficient_data():
    s = RSIStrategy(params={"period": 14, "oversold": 30.0, "overbought": 70.0, "amount": 0.5})
    # Only 1 tick → _rsi returns 50.0 (neutral)
    signals = await s.execute(_tick(50_000.0), asset_num=0)
    assert signals == []


@pytest.mark.asyncio
async def test_execute_long_signal_when_rsi_below_oversold():
    """All declining prices → RSI near 0 → LONG signal."""
    s = RSIStrategy(params={"period": 5, "oversold": 30.0, "overbought": 70.0, "amount": 0.5})
    for price in [100.0, 99.0, 98.0, 97.0, 96.0, 95.0]:
        s._closes.append(price)
    signals = await s.execute(_tick(94.0), asset_num=0)
    assert len(signals) == 1
    assert signals[0].execute == SignalSide.LONG


@pytest.mark.asyncio
async def test_execute_short_signal_when_rsi_above_overbought():
    """All rising prices → RSI near 100 → SHORT signal."""
    s = RSIStrategy(params={"period": 5, "oversold": 30.0, "overbought": 70.0, "amount": 0.5})
    for price in [90.0, 91.0, 92.0, 93.0, 94.0, 95.0]:
        s._closes.append(price)
    signals = await s.execute(_tick(96.0), asset_num=0)
    assert len(signals) == 1
    assert signals[0].execute == SignalSide.SHORT


@pytest.mark.asyncio
async def test_execute_no_signal_in_neutral_zone():
    """Alternating prices → RSI ≈ 50 → no signal."""
    s = RSIStrategy(params={"period": 5, "oversold": 30.0, "overbought": 70.0, "amount": 0.5})
    for price in [100.0, 101.0, 100.0, 101.0, 100.0, 101.0]:
        s._closes.append(price)
    signals = await s.execute(_tick(100.0), asset_num=0)
    assert signals == []


@pytest.mark.asyncio
async def test_execute_signal_has_correct_amount():
    s = RSIStrategy(params={"period": 5, "oversold": 30.0, "overbought": 70.0, "amount": 0.3})
    for price in [100.0, 99.0, 98.0, 97.0, 96.0, 95.0]:
        s._closes.append(price)
    signals = await s.execute(_tick(94.0), asset_num=0)
    assert signals[0].amount == pytest.approx(0.3)


@pytest.mark.asyncio
async def test_execute_signal_has_correct_tp_sl():
    s = RSIStrategy(params={"period": 5, "oversold": 30.0, "overbought": 70.0,
                            "amount": 0.5, "tp_pct": 0.05, "sl_pct": 0.02})
    for price in [100.0, 99.0, 98.0, 97.0, 96.0, 95.0]:
        s._closes.append(price)
    signals = await s.execute(_tick(94.0), asset_num=0)
    assert signals[0].tp_pct == pytest.approx(0.05)
    assert signals[0].sl_pct == pytest.approx(0.02)


@pytest.mark.asyncio
async def test_execute_signal_price_equals_tick_close():
    s = RSIStrategy(params={"period": 5, "oversold": 30.0, "overbought": 70.0, "amount": 0.5})
    for price in [100.0, 99.0, 98.0, 97.0, 96.0, 95.0]:
        s._closes.append(price)
    tick_close = 94.0
    signals = await s.execute(_tick(tick_close), asset_num=0)
    assert signals[0].price == tick_close


@pytest.mark.asyncio
async def test_execute_signal_targets_asset_num_zero():
    s = RSIStrategy(params={"period": 5, "oversold": 30.0, "overbought": 70.0, "amount": 0.5})
    for price in [100.0, 99.0, 98.0, 97.0, 96.0, 95.0]:
        s._closes.append(price)
    signals = await s.execute(_tick(94.0), asset_num=0)
    assert signals[0].asset_num == 0
    assert signals[0].exchange_num == 0


@pytest.mark.asyncio
async def test_execute_appends_to_closes_deque():
    s = RSIStrategy(params={"period": 14})
    initial_len = len(s._closes)
    await s.execute(_tick(50_000.0), asset_num=0)
    assert len(s._closes) == initial_len + 1


@pytest.mark.asyncio
async def test_execute_deque_respects_maxlen():
    period = 5
    s = RSIStrategy(params={"period": period})
    maxlen = period + 10  # deque maxlen = period + 10
    for i in range(maxlen + 50):
        await s.execute(_tick(float(100 + i)), asset_num=0)
    assert len(s._closes) <= maxlen
