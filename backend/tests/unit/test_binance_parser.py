"""
Unit tests for BinanceDataFetcher message parsing.
Calls handler methods directly — no WebSocket connections required.
"""
import json
import time
import pytest
from unittest.mock import AsyncMock, patch

from app.services.data_fetcher import (
    AggTradeData,
    FundingRateData,
    LiquidationData,
    MarkPriceData,
    OrderBookData,
    Subscription,
    TickData,
)
from app.services.data_fetcher.binance import BinanceFuturesDataFetcher


def _fetcher(mock_redis) -> BinanceFuturesDataFetcher:
    f = BinanceFuturesDataFetcher()
    f._redis = mock_redis
    f._subscriptions = {
        "btcusdt:1m:futures": Subscription("btcusdt", "1m", "binance", "futures"),
    }
    return f


# ── Kline handler ────────────────────────────────────────────────────

def _kline_msg(symbol: str, interval: str, close: float, is_closed: bool) -> str:
    return json.dumps({
        "stream": f"{symbol.lower()}@kline_{interval}",
        "data": {
            "s": symbol.upper(),
            "k": {
                "t": 1_700_000_000_000,
                "i": interval,
                "o": str(close),
                "h": str(close * 1.001),
                "l": str(close * 0.999),
                "c": str(close),
                "v": "100.0",
                "x": is_closed,
            },
        },
    })


@pytest.mark.asyncio
async def test_handle_kline_closed_bar_emits_tick(mock_redis):
    f = _fetcher(mock_redis)
    received = []
    f.add_callback(AsyncMock(side_effect=lambda t: received.append(t)))
    await f._handle_kline(_kline_msg("BTCUSDT", "1m", 50_000.0, is_closed=True))
    assert len(received) == 1
    tick = received[0]
    assert isinstance(tick, TickData)
    assert tick.symbol == "btcusdt"
    assert tick.close == pytest.approx(50_000.0)
    assert tick.timeframe == "1m"


@pytest.mark.asyncio
async def test_handle_kline_open_bar_emits_with_is_closed_false(mock_redis):
    """Open bars are emitted for real-time chart updates; is_closed distinguishes them."""
    f = _fetcher(mock_redis)
    received = []
    f.add_callback(AsyncMock(side_effect=lambda t: received.append(t)))
    await f._handle_kline(_kline_msg("BTCUSDT", "1m", 50_000.0, is_closed=False))
    assert len(received) == 1
    assert received[0].is_closed is False


@pytest.mark.asyncio
async def test_handle_kline_symbol_is_lowercased(mock_redis):
    f = _fetcher(mock_redis)
    received = []
    f.add_callback(AsyncMock(side_effect=lambda t: received.append(t)))
    await f._handle_kline(_kline_msg("ETHUSDT", "5m", 3_000.0, is_closed=True))
    assert received[0].symbol == "ethusdt"


@pytest.mark.asyncio
async def test_handle_kline_all_ohlcv_fields_present(mock_redis):
    f = _fetcher(mock_redis)
    received = []
    f.add_callback(AsyncMock(side_effect=lambda t: received.append(t)))
    await f._handle_kline(_kline_msg("BTCUSDT", "1m", 50_000.0, is_closed=True))
    tick = received[0]
    assert tick.open > 0
    assert tick.high >= tick.close
    assert tick.low <= tick.close
    assert tick.volume == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_handle_kline_invalid_json_does_not_raise(mock_redis):
    f = _fetcher(mock_redis)
    await f._handle_kline("{invalid json")  # must not propagate exception


# ── Mark price handler ───────────────────────────────────────────────

def _mark_price_msg(symbol: str, mark: float, index: float, funding: float) -> str:
    return json.dumps({
        "stream": f"{symbol.lower()}@markPrice@1s",
        "data": {
            "e": "markPriceUpdate",
            "s": symbol.upper(),
            "T": 1_700_000_000_000,
            "p": str(mark),
            "i": str(index),
            "r": str(funding),
        },
    })


@pytest.mark.asyncio
async def test_handle_mark_price_emits_mark_price(mock_redis):
    f = _fetcher(mock_redis)
    received = []
    f.add_mark_price_callback(AsyncMock(side_effect=lambda d: received.append(d)))
    await f._handle_mark_price(_mark_price_msg("BTCUSDT", 50_000.0, 49_900.0, 0.0001))
    assert len(received) == 1
    mp = received[0]
    assert isinstance(mp, MarkPriceData)
    assert mp.price == pytest.approx(50_000.0)
    assert mp.index_price == pytest.approx(49_900.0)
    assert mp.symbol == "btcusdt"


@pytest.mark.asyncio
async def test_handle_mark_price_emits_funding_rate(mock_redis):
    f = _fetcher(mock_redis)
    received = []
    f.add_funding_callback(AsyncMock(side_effect=lambda d: received.append(d)))
    await f._handle_mark_price(_mark_price_msg("BTCUSDT", 50_000.0, 49_900.0, 0.0001))
    assert len(received) == 1
    fr = received[0]
    assert isinstance(fr, FundingRateData)
    assert fr.rate == pytest.approx(0.0001)


@pytest.mark.asyncio
async def test_handle_mark_price_missing_funding_no_callback(mock_redis):
    """If funding rate field 'r' is absent, only mark price callback fires."""
    f = _fetcher(mock_redis)
    funding_received = []
    f.add_funding_callback(AsyncMock(side_effect=lambda d: funding_received.append(d)))
    msg = json.dumps({
        "data": {
            "e": "markPriceUpdate",
            "s": "BTCUSDT",
            "T": 1_700_000_000_000,
            "p": "50000.0",
            "i": "49900.0",
            # "r" absent
        }
    })
    await f._handle_mark_price(msg)
    assert len(funding_received) == 0


# ── AggTrade handler ─────────────────────────────────────────────────

def _agg_trade_msg(symbol: str, price: float, qty: float, buyer_maker: bool) -> str:
    return json.dumps({
        "stream": f"{symbol.lower()}@aggTrade",
        "data": {
            "e": "aggTrade",
            "s": symbol.upper(),
            "T": 1_700_000_000_000,
            "p": str(price),
            "q": str(qty),
            "m": buyer_maker,
        },
    })


@pytest.mark.asyncio
async def test_handle_agg_trade_emits_correct_fields(mock_redis):
    f = _fetcher(mock_redis)
    received = []
    f.add_agg_trade_callback(AsyncMock(side_effect=lambda d: received.append(d)))
    await f._handle_agg_trade(_agg_trade_msg("BTCUSDT", 50_000.0, 0.01, False))
    assert len(received) == 1
    trade = received[0]
    assert isinstance(trade, AggTradeData)
    assert trade.price == pytest.approx(50_000.0)
    assert trade.quantity == pytest.approx(0.01)
    assert trade.is_buyer_maker is False
    assert trade.symbol == "btcusdt"


@pytest.mark.asyncio
async def test_handle_agg_trade_buyer_maker_true(mock_redis):
    f = _fetcher(mock_redis)
    received = []
    f.add_agg_trade_callback(AsyncMock(side_effect=lambda d: received.append(d)))
    await f._handle_agg_trade(_agg_trade_msg("BTCUSDT", 50_000.0, 0.01, True))
    assert received[0].is_buyer_maker is True


@pytest.mark.asyncio
async def test_handle_agg_trade_wrong_event_type_no_emit(mock_redis):
    f = _fetcher(mock_redis)
    received = []
    f.add_agg_trade_callback(AsyncMock(side_effect=lambda d: received.append(d)))
    msg = json.dumps({"data": {"e": "kline", "s": "BTCUSDT"}})
    await f._handle_agg_trade(msg)
    assert len(received) == 0


# ── Liquidation handler ───────────────────────────────────────────────

def _liq_msg(symbol: str, side: str, price: float, qty: float) -> str:
    """side: 'BUY' or 'SELL' (Binance convention for liquidation order direction)."""
    return json.dumps({
        "o": {
            "s": symbol.upper(),
            "S": side,
            "T": 1_700_000_000_000,
            "p": str(price),
            "q": str(qty),
        }
    })


@pytest.mark.asyncio
async def test_handle_liquidation_buy_side_maps_to_short_liq(mock_redis):
    """A BUY liquidation order closes a SHORT position → 'short_liq'."""
    f = _fetcher(mock_redis)
    received = []
    f.add_liquidation_callback(AsyncMock(side_effect=lambda d: received.append(d)))
    subscribed = {"btcusdt"}
    await f._handle_liquidation(_liq_msg("BTCUSDT", "BUY", 50_000.0, 1.0), subscribed)
    assert received[0].side == "short_liq"


@pytest.mark.asyncio
async def test_handle_liquidation_sell_side_maps_to_long_liq(mock_redis):
    """A SELL liquidation order closes a LONG position → 'long_liq'."""
    f = _fetcher(mock_redis)
    received = []
    f.add_liquidation_callback(AsyncMock(side_effect=lambda d: received.append(d)))
    subscribed = {"btcusdt"}
    await f._handle_liquidation(_liq_msg("BTCUSDT", "SELL", 50_000.0, 1.0), subscribed)
    assert received[0].side == "long_liq"


@pytest.mark.asyncio
async def test_handle_liquidation_unsubscribed_symbol_filtered(mock_redis):
    """Symbols not in subscribed_symbols should be silently dropped."""
    f = _fetcher(mock_redis)
    received = []
    f.add_liquidation_callback(AsyncMock(side_effect=lambda d: received.append(d)))
    subscribed = {"ethusdt"}  # only ETH subscribed
    await f._handle_liquidation(_liq_msg("BTCUSDT", "BUY", 50_000.0, 1.0), subscribed)
    assert len(received) == 0


@pytest.mark.asyncio
async def test_handle_liquidation_all_symbols_when_empty_set(mock_redis):
    """Empty subscribed_symbols means no filter (all symbols pass)."""
    f = _fetcher(mock_redis)
    received = []
    f.add_liquidation_callback(AsyncMock(side_effect=lambda d: received.append(d)))
    await f._handle_liquidation(_liq_msg("BTCUSDT", "BUY", 50_000.0, 1.0), set())
    assert len(received) == 1


@pytest.mark.asyncio
async def test_handle_liquidation_correct_price_and_qty(mock_redis):
    f = _fetcher(mock_redis)
    received = []
    f.add_liquidation_callback(AsyncMock(side_effect=lambda d: received.append(d)))
    await f._handle_liquidation(_liq_msg("BTCUSDT", "BUY", 49_500.0, 2.5), {"btcusdt"})
    assert received[0].price == pytest.approx(49_500.0)
    assert received[0].quantity == pytest.approx(2.5)


# ── Order book handler ────────────────────────────────────────────────

def _depth_msg(symbol: str) -> str:
    return json.dumps({
        "stream": f"{symbol.lower()}@depth20@100ms",
        "data": {
            "T": 1_700_000_000_000,
            "b": [["50000", "1"], ["49999", "2"]],
            "a": [["50001", "1"], ["50002", "2"]],
        },
    })


@pytest.mark.asyncio
async def test_handle_orderbook_writes_to_redis(mock_redis):
    f = _fetcher(mock_redis)
    await f._handle_orderbook(_depth_msg("BTCUSDT"))
    mock_redis.set.assert_called_once()


@pytest.mark.asyncio
async def test_handle_orderbook_extracts_symbol_from_stream_name(mock_redis):
    f = _fetcher(mock_redis)
    await f._handle_orderbook(_depth_msg("ETHUSDT"))
    key = mock_redis.set.call_args.args[0]
    assert "ethusdt" in key


@pytest.mark.asyncio
async def test_handle_orderbook_stores_bids_and_asks(mock_redis):
    f = _fetcher(mock_redis)
    await f._handle_orderbook(_depth_msg("BTCUSDT"))
    raw_json = mock_redis.set.call_args.args[1]
    payload = json.loads(raw_json)
    assert "bids" in payload
    assert "asks" in payload
    assert len(payload["bids"]) == 2
    assert len(payload["asks"]) == 2
