"""
Unit tests for BinanceFuturesDataFetcher — URL configuration and task-set.
Handler parsing tests live in test_binance_parser.py.
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.data_fetcher import Subscription
from app.services.data_fetcher.binance import (
    BinanceFuturesDataFetcher,
    _FUTURES_WS_MAIN,
    _FUTURES_WS_TEST,
    _FUTURES_WS_SINGLE_MAIN,
    _FUTURES_WS_SINGLE_TEST,
    _FUTURES_REST_MAIN,
    _FUTURES_REST_TEST,
)

_SUB = Subscription("btcusdt", "1m", "binance", "futures")
_KEY = "btcusdt:1m:futures"


# ── URL / endpoint configuration ─────────────────────────────────────────

def test_futures_testnet_ws_url():
    assert BinanceFuturesDataFetcher(testnet=True)._ws_base == _FUTURES_WS_TEST


def test_futures_mainnet_ws_url():
    assert BinanceFuturesDataFetcher(testnet=False)._ws_base == _FUTURES_WS_MAIN


def test_futures_testnet_ws_single_url():
    assert BinanceFuturesDataFetcher(testnet=True)._ws_single == _FUTURES_WS_SINGLE_TEST


def test_futures_mainnet_ws_single_url():
    assert BinanceFuturesDataFetcher(testnet=False)._ws_single == _FUTURES_WS_SINGLE_MAIN


def test_futures_testnet_rest_url():
    assert BinanceFuturesDataFetcher(testnet=True)._rest_base == _FUTURES_REST_TEST


def test_futures_mainnet_rest_url():
    assert BinanceFuturesDataFetcher(testnet=False)._rest_base == _FUTURES_REST_MAIN


def test_futures_klines_path():
    assert BinanceFuturesDataFetcher()._klines_path == "/fapi/v1/klines"


# ── Combined stream URL ───────────────────────────────────────────────────

def test_futures_all_streams_url_uses_ws_base():
    f = BinanceFuturesDataFetcher(testnet=False)
    f._subscriptions = {_KEY: _SUB}
    url = f._all_streams_url()
    assert url is not None
    assert url.startswith(_FUTURES_WS_MAIN)


def test_futures_all_streams_url_contains_kline():
    f = BinanceFuturesDataFetcher()
    f._subscriptions = {_KEY: _SUB}
    url = f._all_streams_url()
    assert "btcusdt@kline_1m" in url


def test_futures_all_streams_url_contains_agg_trade():
    f = BinanceFuturesDataFetcher()
    f._subscriptions = {_KEY: _SUB}
    url = f._all_streams_url()
    assert "btcusdt@aggTrade" in url


def test_futures_all_streams_url_contains_depth():
    _sub_depth = Subscription("btcusdt", "1m", "binance", "futures", subscribe_depth=True)
    _key_depth = "btcusdt:1m:futures"
    f = BinanceFuturesDataFetcher()
    f._subscriptions = {_key_depth: _sub_depth}
    url = f._all_streams_url()
    assert "btcusdt@depth20@100ms" in url


def test_futures_all_streams_url_contains_mark_price():
    f = BinanceFuturesDataFetcher()
    f._subscriptions = {_KEY: _SUB}
    url = f._all_streams_url()
    assert "btcusdt@markPrice@1s" in url


def test_futures_liquidation_url_uses_single_endpoint():
    f = BinanceFuturesDataFetcher(testnet=False)
    url = f"{f._ws_single}/!forceOrder@arr"
    assert "fstream.binance.com/ws" in url
    assert "!forceOrder@arr" in url


def test_futures_liquidation_url_testnet_uses_single_endpoint():
    f = BinanceFuturesDataFetcher(testnet=True)
    url = f"{f._ws_single}/!forceOrder@arr"
    assert "stream.binancefuture.com/ws" in url


# ── Task-set verification ─────────────────────────────────────────────────

def test_futures_task_set_includes_all_streams():
    with patch("asyncio.create_task", return_value=MagicMock()):
        f = BinanceFuturesDataFetcher()
        f._subscriptions = {_KEY: _SUB}
        f._launch_all_tasks()

    expected = {"backfill", "stream", "oi_loop", "liquidation"}
    assert expected == set(f._tasks.keys())


def test_futures_no_tasks_when_no_subscriptions():
    with patch("asyncio.create_task", return_value=MagicMock()):
        f = BinanceFuturesDataFetcher()
        f._subscriptions = {}
        f._launch_all_tasks()

    assert f._tasks == {}
