"""
Unit tests for PairTradeStrategy (multi-asset BTC/ETH mean reversion).
InternalDataFetcher is mocked — no DB required.
"""
import pytest
import numpy as np
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.data_fetcher import TickData
from app.services.strategy_executer import SignalSide
from strategies.example_pair_trade import PairTradeStrategy


def _tick(close: float, asset_slug: str = "btcusdt") -> TickData:
    return TickData(
        asset_slug=asset_slug, timeframe="1h",
        time=1_700_000_000_000,
        open=close, high=close * 1.001, low=close * 0.999,
        close=close, volume=100.0,
    )


def _klines(prices: list[float]):
    """Build fake kline objects with a .close attribute."""
    class _K:
        def __init__(self, c): self.close = c
    return [_K(p) for p in prices]


def _mock_fetcher(btc_closes: list[float], eth_closes: list[float]) -> AsyncMock:
    """Return an AsyncMock InternalDataFetcher that serves fixed klines."""
    instance = AsyncMock()
    instance.get_klines = AsyncMock(side_effect=[
        _klines(btc_closes),
        _klines(eth_closes),
    ])
    return instance


# ── Static checks ─────────────────────────────────────────────────────

def test_pair_trade_id_is_string():
    assert isinstance(PairTradeStrategy().id, str)


def test_pair_trade_parameter_schema_names():
    names = {p.name for p in PairTradeStrategy().parameter_schema}
    assert names == {"lookback", "z_threshold", "amount"}


def test_pair_trade_subscriptions():
    subs = PairTradeStrategy().subscriptions
    slugs = [s.asset_slug for s in subs]
    assert "btcusdt" in slugs
    assert "ethusdt" in slugs
    assert len(subs) == 2


def test_pair_trade_btc_is_trigger_asset():
    subs = PairTradeStrategy().subscriptions
    btc_sub = next(s for s in subs if s.asset_slug == "btcusdt")
    assert btc_sub.tick_process is True


def test_pair_trade_eth_is_not_trigger():
    subs = PairTradeStrategy().subscriptions
    eth_sub = next(s for s in subs if s.asset_slug == "ethusdt")
    assert eth_sub.tick_process is False


def test_pair_trade_is_not_legacy():
    assert PairTradeStrategy._is_legacy() is False


# ── execute() routing ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_skips_non_trigger_asset():
    s = PairTradeStrategy()
    signals = await s.execute(_tick(60_000.0), asset_num=1)
    assert signals == []


@pytest.mark.asyncio
async def test_execute_skips_non_trigger_asset_2():
    s = PairTradeStrategy()
    signals = await s.execute(_tick(60_000.0), asset_num=5)
    assert signals == []


# ── Insufficient data ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_returns_empty_when_klines_too_short():
    s = PairTradeStrategy(params={"lookback": 20, "z_threshold": 2.0, "amount": 0.3})
    with patch("strategies.example_pair_trade.InternalDataFetcher") as MockFetcher:
        MockFetcher.return_value = _mock_fetcher(
            btc_closes=[60_000.0] * 10,  # < lookback=20
            eth_closes=[2_000.0] * 10,
        )
        signals = await s.execute(_tick(60_000.0), asset_num=0)
    assert signals == []


@pytest.mark.asyncio
async def test_execute_returns_empty_when_ratio_std_is_zero():
    """Constant ratio → std=0 → guard triggers → []."""
    lookback = 5
    s = PairTradeStrategy(params={"lookback": lookback, "z_threshold": 2.0, "amount": 0.3})
    btc = [60_000.0] * (lookback + 5)
    eth = [2_000.0] * (lookback + 5)
    with patch("strategies.example_pair_trade.InternalDataFetcher") as MockFetcher:
        MockFetcher.return_value = _mock_fetcher(btc, eth)
        signals = await s.execute(_tick(60_000.0), asset_num=0)
    assert signals == []


# ── Signal direction ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_long_btc_short_eth_when_ratio_is_very_low():
    """
    BTC cheap relative to ETH → z << -threshold → LONG BTC (0) + SHORT ETH (1).

    Historical BTC prices alternate so std > 0.
    Then a very low current BTC price produces z well below -2.
    """
    lookback = 5
    s = PairTradeStrategy(params={"lookback": lookback, "z_threshold": 2.0, "amount": 0.3})

    # BTC: alternates 59k/61k → ratios ≈ 29.5/30.5 (mean=30, std≈0.5)
    # ETH: constant 2000
    btc = [59_000, 61_000, 59_000, 61_000, 59_000,
           61_000, 59_000, 61_000, 59_000, 61_000]
    eth = [2_000.0] * 10

    # current tick.close = 40000 → current_ratio = 40000/2000 = 20
    # z = (20 - 30) / 0.5 = -20 → well below -2
    tick = _tick(40_000.0)

    with patch("strategies.example_pair_trade.InternalDataFetcher") as MockFetcher:
        MockFetcher.return_value = _mock_fetcher(btc, eth)
        signals = await s.execute(tick, asset_num=0)

    assert len(signals) == 2
    sides = {sig.asset_num: sig.execute for sig in signals}
    assert sides[0] == SignalSide.LONG   # long BTC
    assert sides[1] == SignalSide.SHORT  # short ETH


@pytest.mark.asyncio
async def test_execute_short_btc_long_eth_when_ratio_is_very_high():
    """BTC expensive relative to ETH → z >> threshold → SHORT BTC + LONG ETH."""
    lookback = 5
    s = PairTradeStrategy(params={"lookback": lookback, "z_threshold": 2.0, "amount": 0.3})

    btc = [59_000, 61_000, 59_000, 61_000, 59_000,
           61_000, 59_000, 61_000, 59_000, 61_000]
    eth = [2_000.0] * 10

    # current tick.close = 80000 → ratio = 40 → z = (40-30)/0.5 = 20
    tick = _tick(80_000.0)

    with patch("strategies.example_pair_trade.InternalDataFetcher") as MockFetcher:
        MockFetcher.return_value = _mock_fetcher(btc, eth)
        signals = await s.execute(tick, asset_num=0)

    assert len(signals) == 2
    sides = {sig.asset_num: sig.execute for sig in signals}
    assert sides[0] == SignalSide.SHORT  # short BTC
    assert sides[1] == SignalSide.LONG   # long ETH


@pytest.mark.asyncio
async def test_execute_no_signal_in_neutral_zone():
    """Current ratio ≈ mean → |z| < threshold → []."""
    lookback = 5
    s = PairTradeStrategy(params={"lookback": lookback, "z_threshold": 2.0, "amount": 0.3})

    btc = [59_000, 61_000, 59_000, 61_000, 59_000,
           61_000, 59_000, 61_000, 59_000, 61_000]
    eth = [2_000.0] * 10

    # ratio = 60000/2000 = 30 = mean → z = 0
    tick = _tick(60_000.0)

    with patch("strategies.example_pair_trade.InternalDataFetcher") as MockFetcher:
        MockFetcher.return_value = _mock_fetcher(btc, eth)
        signals = await s.execute(tick, asset_num=0)

    assert signals == []


@pytest.mark.asyncio
async def test_execute_signal_uses_configured_amount():
    lookback = 5
    s = PairTradeStrategy(params={"lookback": lookback, "z_threshold": 2.0, "amount": 0.25})
    btc = [59_000, 61_000, 59_000, 61_000, 59_000,
           61_000, 59_000, 61_000, 59_000, 61_000]
    eth = [2_000.0] * 10
    with patch("strategies.example_pair_trade.InternalDataFetcher") as MockFetcher:
        MockFetcher.return_value = _mock_fetcher(btc, eth)
        signals = await s.execute(_tick(40_000.0), asset_num=0)
    assert all(sig.amount == pytest.approx(0.25) for sig in signals)


@pytest.mark.asyncio
async def test_execute_signals_target_futures_market():
    lookback = 5
    s = PairTradeStrategy(params={"lookback": lookback, "z_threshold": 2.0, "amount": 0.3})
    btc = [59_000, 61_000, 59_000, 61_000, 59_000,
           61_000, 59_000, 61_000, 59_000, 61_000]
    eth = [2_000.0] * 10
    with patch("strategies.example_pair_trade.InternalDataFetcher") as MockFetcher:
        MockFetcher.return_value = _mock_fetcher(btc, eth)
        signals = await s.execute(_tick(40_000.0), asset_num=0)
    assert all(sig.market_type == "futures" for sig in signals)
