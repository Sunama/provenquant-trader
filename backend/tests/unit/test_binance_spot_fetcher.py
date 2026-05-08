"""
Unit tests for BinanceSpotDataFetcher — URL config, task-set, and handler parsing.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.data_fetcher import AggTradeData, Subscription, TickData
from app.services.data_fetcher.binance_spot import (
    BinanceSpotDataFetcher,
    _SPOT_WS_MAIN,
    _SPOT_REST_MAIN,
)

_SUB = Subscription("ethusdt", "1m", "binance", "spot")
_KEY = "ethusdt:1m:spot"


def _fetcher(mock_redis) -> BinanceSpotDataFetcher:
    f = BinanceSpotDataFetcher()
    f._redis = mock_redis
    f._subscriptions = {_KEY: _SUB}
    return f


# ── URL / endpoint config ─────────────────────────────────────────────────

def test_spot_ws_url_is_always_mainnet_when_testnet_true():
    assert BinanceSpotDataFetcher(testnet=True)._ws_base == _SPOT_WS_MAIN


def test_spot_ws_url_is_always_mainnet_when_testnet_false():
    assert BinanceSpotDataFetcher(testnet=False)._ws_base == _SPOT_WS_MAIN


def test_spot_rest_url_is_always_mainnet():
    assert BinanceSpotDataFetcher(testnet=True)._rest_base == _SPOT_REST_MAIN
    assert BinanceSpotDataFetcher(testnet=False)._rest_base == _SPOT_REST_MAIN


def test_spot_klines_path_is_api_v3():
    assert BinanceSpotDataFetcher()._klines_path == "/api/v3/klines"


# ── Combined stream URL ───────────────────────────────────────────────────

def test_spot_all_streams_url_uses_ws_base():
    f = BinanceSpotDataFetcher()
    f._subscriptions = {_KEY: _SUB}
    url = f._all_streams_url()
    assert url is not None
    assert url.startswith(_SPOT_WS_MAIN)


def test_spot_all_streams_url_contains_kline():
    f = BinanceSpotDataFetcher()
    f._subscriptions = {_KEY: _SUB}
    url = f._all_streams_url()
    assert "ethusdt@kline_1m" in url


def test_spot_all_streams_url_contains_agg_trade():
    f = BinanceSpotDataFetcher()
    f._subscriptions = {_KEY: _SUB}
    url = f._all_streams_url()
    assert "ethusdt@aggTrade" in url


def test_spot_all_streams_url_contains_depth():
    f = BinanceSpotDataFetcher()
    f._subscriptions = {_KEY: _SUB}
    url = f._all_streams_url()
    assert "ethusdt@depth20@100ms" in url


def test_spot_all_streams_url_excludes_mark_price():
    f = BinanceSpotDataFetcher()
    f._subscriptions = {_KEY: _SUB}
    url = f._all_streams_url()
    assert "@markPrice" not in url


# ── Task-set verification ─────────────────────────────────────────────────

def test_spot_task_set_has_correct_keys():
    with patch("asyncio.create_task", return_value=MagicMock()):
        f = BinanceSpotDataFetcher()
        f._subscriptions = {_KEY: _SUB}
        f._launch_all_tasks()

    assert set(f._tasks.keys()) == {"backfill", "stream"}


def test_spot_task_set_excludes_futures_only_tasks():
    with patch("asyncio.create_task", return_value=MagicMock()):
        f = BinanceSpotDataFetcher()
        f._subscriptions = {_KEY: _SUB}
        f._launch_all_tasks()

    for name in ("oi_loop", "mark_price", "liquidation"):
        assert name not in f._tasks, f"Spot should not have task '{name}'"


def test_spot_no_tasks_when_no_subscriptions():
    with patch("asyncio.create_task", return_value=MagicMock()):
        f = BinanceSpotDataFetcher()
        f._subscriptions = {}
        f._launch_all_tasks()

    assert f._tasks == {}


# ── Kline handler ─────────────────────────────────────────────────────────

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
                "v": "200.0",
                "x": is_closed,
            },
        },
    })


@pytest.mark.asyncio
async def test_spot_handle_kline_closed_bar_emits_tick(mock_redis):
    f = _fetcher(mock_redis)
    received = []
    f.add_callback(AsyncMock(side_effect=lambda t: received.append(t)))
    await f._handle_kline(_kline_msg("ETHUSDT", "1m", 3_000.0, is_closed=True))
    assert len(received) == 1
    tick = received[0]
    assert isinstance(tick, TickData)
    assert tick.asset_slug == "ethusdt"
    assert tick.close == pytest.approx(3_000.0)


@pytest.mark.asyncio
async def test_spot_handle_kline_open_bar_does_not_emit(mock_redis):
    f = _fetcher(mock_redis)
    received = []
    f.add_callback(AsyncMock(side_effect=lambda t: received.append(t)))
    await f._handle_kline(_kline_msg("ETHUSDT", "1m", 3_000.0, is_closed=False))
    assert len(received) == 0


# ── AggTrade handler ──────────────────────────────────────────────────────

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
async def test_spot_handle_agg_trade_emits_correct_fields(mock_redis):
    f = _fetcher(mock_redis)
    received = []
    f.add_agg_trade_callback(AsyncMock(side_effect=lambda d: received.append(d)))
    await f._handle_agg_trade(_agg_trade_msg("ETHUSDT", 3_000.0, 0.5, False))
    assert len(received) == 1
    trade = received[0]
    assert isinstance(trade, AggTradeData)
    assert trade.price == pytest.approx(3_000.0)
    assert trade.quantity == pytest.approx(0.5)
    assert trade.asset_slug == "ethusdt"
    assert trade.is_buyer_maker is False


# ── Order book handler ────────────────────────────────────────────────────

def _depth_msg(symbol: str) -> str:
    return json.dumps({
        "stream": f"{symbol.lower()}@depth20@100ms",
        "data": {
            "T": 1_700_000_000_000,
            "b": [["3000", "1"], ["2999", "2"]],
            "a": [["3001", "1"], ["3002", "2"]],
        },
    })


@pytest.mark.asyncio
async def test_spot_handle_orderbook_writes_to_redis(mock_redis):
    f = _fetcher(mock_redis)
    await f._handle_orderbook(_depth_msg("ETHUSDT"))
    mock_redis.set.assert_called_once()


@pytest.mark.asyncio
async def test_spot_handle_orderbook_key_contains_symbol(mock_redis):
    f = _fetcher(mock_redis)
    await f._handle_orderbook(_depth_msg("ETHUSDT"))
    key = mock_redis.set.call_args.args[0]
    assert "ethusdt" in key
