from __future__ import annotations

from app.services.data_fetcher.binance import BinanceBaseDataFetcher

_SPOT_WS_MAIN  = "wss://stream.binance.com:9443/stream"
_SPOT_WS_TEST  = "wss://testnet.binance.vision/stream"
_SPOT_REST_MAIN = "https://api.binance.com"
_SPOT_REST_TEST = "https://testnet.binance.vision"


class BinanceSpotDataFetcher(BinanceBaseDataFetcher):
    """
    Binance Spot WebSocket streams.

    Spot does not have markPrice, fundingRate, or liquidation streams — those are
    Futures-only. Only kline, aggTrade, orderbook, and OI polling (disabled for Spot)
    are active.

    Testnet: testnet.binance.vision
    Mainnet: stream.binance.com:9443
    """

    @property
    def _ws_base(self) -> str:
        return _SPOT_WS_TEST if self._testnet else _SPOT_WS_MAIN

    @property
    def _rest_base(self) -> str:
        return _SPOT_REST_TEST if self._testnet else _SPOT_REST_MAIN

    def _launch_all_tasks(self) -> None:
        if not self._subscriptions:
            return
        # Spot: backfill, kline, aggTrade, orderbook only.
        # No markPrice, fundingRate, liquidation, or OI (Futures-only concepts).
        import asyncio
        self._tasks["backfill"]  = asyncio.create_task(self._backfill_task())
        self._tasks["kline"]     = asyncio.create_task(self._kline_task())
        self._tasks["agg_trade"] = asyncio.create_task(self._agg_trade_task())
        self._tasks["orderbook"] = asyncio.create_task(self._orderbook_task())
