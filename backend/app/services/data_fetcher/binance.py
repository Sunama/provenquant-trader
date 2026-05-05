from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import websockets

from app.services.data_fetcher import DataFetcher, Subscription, TickData

logger = logging.getLogger(__name__)

# Binance timeframe → WebSocket interval string
_TF_MAP = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m",
    "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d",
}

_WS_BASE = "wss://fstream.binance.com/stream"  # futures stream (perpetual)


class BinanceDataFetcher(DataFetcher):
    """
    Streams closed kline bars from Binance USDT-M Futures WebSocket.

    Each active subscription maps to one combined stream URL.
    When subscriptions change, the connection is torn down and rebuilt
    (Binance combined streams don't support live subscribe/unsubscribe cleanly).
    """

    def __init__(self, testnet: bool = False) -> None:
        super().__init__()
        self._testnet = testnet
        self._ws_task: asyncio.Task | None = None
        self._ws = None

    # ── DataFetcher interface ─────────────────────────────────────

    async def _connect(self) -> None:
        self._ws_task = asyncio.create_task(self._stream_loop())

    async def _disconnect(self) -> None:
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()

    async def _subscribe_symbols(self, subscriptions: list[Subscription]) -> None:
        # Restart stream with new full subscription set
        await self._disconnect()
        self._ws_task = asyncio.create_task(self._stream_loop())

    async def _unsubscribe_symbols(self, subscriptions: list[Subscription]) -> None:
        await self._disconnect()
        if self._subscriptions:
            self._ws_task = asyncio.create_task(self._stream_loop())

    # ── Internal streaming ────────────────────────────────────────

    def _build_url(self) -> str | None:
        if not self._subscriptions:
            return None
        streams = []
        for sub in self._subscriptions.values():
            symbol = sub.asset_slug.lower()  # e.g. "btcusdt"
            interval = _TF_MAP.get(sub.timeframe, "1m")
            streams.append(f"{symbol}@kline_{interval}")
        return f"{_WS_BASE}?streams={'/'.join(streams)}"

    async def _stream_loop(self) -> None:
        while self._running:
            url = self._build_url()
            if not url:
                await asyncio.sleep(1)
                continue

            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                    self._ws = ws
                    logger.info(f"BinanceDataFetcher connected: {len(self._subscriptions)} streams")
                    async for raw in ws:
                        if not self._running:
                            break
                        await self._handle_message(raw)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("BinanceDataFetcher stream error, reconnecting in 5s")
                await asyncio.sleep(5)

    async def _handle_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
            data = msg.get("data", msg)
            kline = data.get("k")
            if not kline:
                return

            # Only emit on bar close
            if not kline.get("x"):
                return

            symbol = data.get("s", "").lower()  # e.g. "BTCUSDT" → "btcusdt"
            interval = kline.get("i", "1m")
            timeframe = interval  # already in our format

            tick = TickData(
                asset_slug=symbol,
                timeframe=timeframe,
                time=int(kline["t"]),
                open=float(kline["o"]),
                high=float(kline["h"]),
                low=float(kline["l"]),
                close=float(kline["c"]),
                volume=float(kline["v"]),
            )
            await self._emit(tick)

        except Exception:
            logger.exception("Error handling Binance message")
