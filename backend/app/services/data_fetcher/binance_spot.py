from __future__ import annotations

import asyncio

from app.services.data_fetcher.binance import BinanceBaseDataFetcher

_SPOT_WS_MAIN   = "wss://stream.binance.com:9443/stream"
_SPOT_REST_MAIN = "https://api.binance.com"


class BinanceSpotDataFetcher(BinanceBaseDataFetcher):
    """
    Binance Spot WebSocket streams.

    Always connects to mainnet regardless of the testnet flag: the Spot testnet
    (testnet.binance.vision) only supports the order-placement API, not live
    WebSocket market-data streams. Paper strategies still need real price data.

    Spot does not have markPrice, fundingRate, liquidation, or OI streams.
    """

    @property
    def _ws_base(self) -> str:
        return _SPOT_WS_MAIN

    @property
    def _rest_base(self) -> str:
        return _SPOT_REST_MAIN

    @property
    def _klines_path(self) -> str:
        return "/api/v3/klines"

    def _launch_all_tasks(self) -> None:
        if not self._subscriptions:
            return
        self._tasks["backfill"] = asyncio.create_task(self._backfill_task())
        self._tasks["stream"]   = asyncio.create_task(self._stream_task())
