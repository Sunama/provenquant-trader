"""
Unit tests for BinanceOptionsDataFetcher — mark price and index stream handlers,
WebSocket URL, and task configuration.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.data_fetcher import MarkPriceData, Subscription, TickData
from app.services.data_fetcher.binance_options import (
    BinanceOptionsDataFetcher,
    _WS_BASE,
)

_SUB = Subscription("btc-240628-60000-c", "1s", "binance", "options")
_KEY = "btc-240628-60000-c:1s:options"


def _fetcher(mock_redis) -> BinanceOptionsDataFetcher:
    f = BinanceOptionsDataFetcher()
    f._redis = mock_redis
    f._subscriptions = {_KEY: _SUB}
    return f


def _mark_price_msg(symbol: str, mark: float, index: float) -> str:
    return json.dumps({
        "data": {
            "s": symbol,
            "t": 1_700_000_000_000,
            "mp": str(mark),
            "ip": str(index),
        }
    })


def _mark_price_list_msg(items: list[dict]) -> str:
    return json.dumps({"data": items})


def _index_msg(underlying: str, price: float) -> str:
    return json.dumps({
        "data": {
            "s": underlying,
            "t": 1_700_000_000_000,
            "p": str(price),
        }
    })


# ── WebSocket URL ──────────────────────────────────────────────────────────

def test_options_ws_base_url():
    assert _WS_BASE == "wss://nbstream.binance.com/eoptions/stream"


# ── Task-set ───────────────────────────────────────────────────────────────

def test_options_task_set():
    with patch("asyncio.create_task", return_value=MagicMock()):
        f = BinanceOptionsDataFetcher()
        f._subscriptions = {_KEY: _SUB}
        f._launch_tasks()

    assert set(f._tasks.keys()) == {"mark_price", "index"}


def test_options_no_tasks_when_no_subscriptions():
    with patch("asyncio.create_task", return_value=MagicMock()):
        f = BinanceOptionsDataFetcher()
        f._subscriptions = {}
        f._launch_tasks()

    assert f._tasks == {}


# ── Mark price handler ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_options_mark_price_emits_mark_price_data(mock_redis):
    f = _fetcher(mock_redis)
    received = []
    f.add_mark_price_callback(AsyncMock(side_effect=lambda d: received.append(d)))
    await f._handle_mark_price(_mark_price_msg("BTC-240628-60000-C", 1_500.0, 67_000.0))
    assert len(received) == 1
    mp = received[0]
    assert isinstance(mp, MarkPriceData)
    assert mp.price == pytest.approx(1_500.0)
    assert mp.index_price == pytest.approx(67_000.0)
    assert mp.market_type == "options"
    assert mp.exchange == "binance_options"


@pytest.mark.asyncio
async def test_options_mark_price_symbol_is_lowercased(mock_redis):
    f = _fetcher(mock_redis)
    received = []
    f.add_mark_price_callback(AsyncMock(side_effect=lambda d: received.append(d)))
    await f._handle_mark_price(_mark_price_msg("BTC-240628-60000-C", 1_500.0, 67_000.0))
    assert received[0].asset_slug == "btc-240628-60000-c"


@pytest.mark.asyncio
async def test_options_mark_price_emits_pseudo_tick(mock_redis):
    f = _fetcher(mock_redis)
    received = []
    f.add_callback(AsyncMock(side_effect=lambda t: received.append(t)))
    await f._handle_mark_price(_mark_price_msg("BTC-240628-60000-C", 1_500.0, 67_000.0))
    assert len(received) == 1
    tick = received[0]
    assert isinstance(tick, TickData)
    assert tick.open == pytest.approx(1_500.0)
    assert tick.high == pytest.approx(1_500.0)
    assert tick.low == pytest.approx(1_500.0)
    assert tick.close == pytest.approx(1_500.0)


@pytest.mark.asyncio
async def test_options_mark_price_no_tick_when_mp_absent(mock_redis):
    f = _fetcher(mock_redis)
    tick_received = []
    f.add_callback(AsyncMock(side_effect=lambda t: tick_received.append(t)))
    msg = json.dumps({"data": {"s": "BTC-240628-60000-C", "t": 1_700_000_000_000}})
    await f._handle_mark_price(msg)
    assert len(tick_received) == 0


@pytest.mark.asyncio
async def test_options_mark_price_processes_list_input(mock_redis):
    f = _fetcher(mock_redis)
    received = []
    f.add_mark_price_callback(AsyncMock(side_effect=lambda d: received.append(d)))
    items = [
        {"s": "BTC-240628-60000-C", "t": 1_700_000_000_000, "mp": "1500.0", "ip": "67000.0"},
        {"s": "BTC-240628-70000-C", "t": 1_700_000_000_000, "mp": "800.0",  "ip": "67000.0"},
    ]
    await f._handle_mark_price(_mark_price_list_msg(items))
    assert len(received) == 2


# ── Index handler ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_options_index_emits_mark_price_data(mock_redis):
    f = _fetcher(mock_redis)
    received = []
    f.add_mark_price_callback(AsyncMock(side_effect=lambda d: received.append(d)))
    await f._handle_index(_index_msg("BTC", 67_000.0))
    assert len(received) == 1
    mp = received[0]
    assert isinstance(mp, MarkPriceData)
    assert mp.price == pytest.approx(67_000.0)
    assert mp.index_price == pytest.approx(67_000.0)


@pytest.mark.asyncio
async def test_options_index_market_type_is_options_index(mock_redis):
    f = _fetcher(mock_redis)
    received = []
    f.add_mark_price_callback(AsyncMock(side_effect=lambda d: received.append(d)))
    await f._handle_index(_index_msg("BTC", 67_000.0))
    assert received[0].market_type == "options_index"


@pytest.mark.asyncio
async def test_options_index_asset_slug_includes_usdt(mock_redis):
    f = _fetcher(mock_redis)
    received = []
    f.add_mark_price_callback(AsyncMock(side_effect=lambda d: received.append(d)))
    await f._handle_index(_index_msg("BTC", 67_000.0))
    assert received[0].asset_slug == "btcusdt"


@pytest.mark.asyncio
async def test_options_index_underlying_is_lowercased(mock_redis):
    f = _fetcher(mock_redis)
    received = []
    f.add_mark_price_callback(AsyncMock(side_effect=lambda d: received.append(d)))
    await f._handle_index(_index_msg("ETH", 3_000.0))
    assert received[0].asset_slug == "ethusdt"
