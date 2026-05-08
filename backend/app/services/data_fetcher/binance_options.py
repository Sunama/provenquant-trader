from __future__ import annotations

import asyncio
import json
import logging
import time

from websockets.asyncio.client import connect as ws_connect

from app.services.data_fetcher import (
    DataFetcher,
    MarkPriceData,
    OpenInterestData,
    Subscription,
    TickData,
)

logger = logging.getLogger(__name__)

_WS_BASE = "wss://nbstream.binance.com/eoptions/stream"
_RECONNECT_DELAY = 5


class BinanceOptionsDataFetcher(DataFetcher):
    """
    Streams Binance European Options (EAPI) data via WebSocket.

    Subscriptions use asset_slug in the form "<underlying>_<expiry>_<strike>_<C|P>"
    e.g. "btc_240628_60000_c"

    Streams per subscribed option:
      {symbol}@index          — index price updates
      {symbol}@markPrice      — mark price + IV
      {symbol}@openInterest   — open interest (no WS native; polled per heartbeat)
    """

    def __init__(self) -> None:
        super().__init__()
        self._tasks: dict[str, asyncio.Task] = {}

    # ── DataFetcher interface ─────────────────────────────────────

    async def _connect(self) -> None:
        self._launch_tasks()

    async def _disconnect(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    async def _subscribe_symbols(self, subscriptions: list[Subscription]) -> None:
        await self._disconnect()
        self._launch_tasks()

    async def _unsubscribe_symbols(self, subscriptions: list[Subscription]) -> None:
        await self._disconnect()
        if self._subscriptions:
            self._launch_tasks()

    # ── Task launcher ─────────────────────────────────────────────

    def _launch_tasks(self) -> None:
        if not self._subscriptions:
            return
        self._tasks["mark_price"] = asyncio.create_task(self._mark_price_task())
        self._tasks["index"] = asyncio.create_task(self._index_task())

    def _option_symbols(self) -> list[str]:
        return list({s.asset_slug.upper() for s in self._subscriptions.values()})

    # ── Mark price + IV stream ────────────────────────────────────

    async def _mark_price_task(self) -> None:
        while self._running:
            symbols = self._option_symbols()
            if not symbols:
                await asyncio.sleep(1)
                continue
            streams = [f"{s}@markPrice" for s in symbols]
            url = f"{_WS_BASE}?streams={'/'.join(streams)}"
            try:
                async with ws_connect(url, ping_interval=20, ping_timeout=10) as ws:
                    logger.info(f"[BinanceOptionsDataFetcher] markPrice connected ({len(symbols)} symbols)")
                    async for raw in ws:
                        if not self._running:
                            break
                        await self._handle_mark_price(raw)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("[BinanceOptionsDataFetcher] markPrice error, reconnecting")
                await asyncio.sleep(_RECONNECT_DELAY)

    async def _handle_mark_price(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
            data = msg.get("data", msg)
            if not isinstance(data, list):
                data = [data]

            for item in data:
                symbol = item.get("s", "").lower()
                ts = int(item.get("t", time.time() * 1000))
                mark = MarkPriceData(
                    asset_slug=symbol,
                    exchange="binance_options",
                    market_type="options",
                    time=ts,
                    price=float(item["mp"]) if item.get("mp") else 0.0,
                    index_price=float(item["ip"]) if item.get("ip") else None,
                )
                await self._emit_mark_price(mark)

                # Emit as pseudo-tick for strategy consumption (close = mark price)
                if item.get("mp"):
                    tick = TickData(
                        asset_slug=symbol,
                        timeframe="1s",
                        time=ts,
                        open=float(item["mp"]),
                        high=float(item["mp"]),
                        low=float(item["mp"]),
                        close=float(item["mp"]),
                        volume=0.0,
                    )
                    await self._emit(tick)
        except Exception:
            logger.exception("[BinanceOptionsDataFetcher] markPrice parse error")

    # ── Index price stream ────────────────────────────────────────

    async def _index_task(self) -> None:
        # Derive unique underlyings (e.g. "BTC", "ETH") from subscribed option symbols
        while self._running:
            symbols = self._option_symbols()
            underlyings = list({s.split("-")[0].lower() if "-" in s else s[:3].lower() for s in symbols})
            if not underlyings:
                await asyncio.sleep(1)
                continue
            # Binance EAPI index stream format: {underlying}@index
            streams = [f"{u}@index" for u in underlyings]
            url = f"{_WS_BASE}?streams={'/'.join(streams)}"
            try:
                async with ws_connect(url, ping_interval=20, ping_timeout=10) as ws:
                    logger.info(f"[BinanceOptionsDataFetcher] index connected ({underlyings})")
                    async for raw in ws:
                        if not self._running:
                            break
                        await self._handle_index(raw)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("[BinanceOptionsDataFetcher] index error, reconnecting")
                await asyncio.sleep(_RECONNECT_DELAY)

    async def _handle_index(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
            data = msg.get("data", msg)
            underlying = data.get("s", "").lower()
            ts = int(data.get("t", time.time() * 1000))
            price = float(data.get("p", 0.0))

            mark = MarkPriceData(
                asset_slug=f"{underlying}usdt",
                exchange="binance_options",
                market_type="options_index",
                time=ts,
                price=price,
                index_price=price,
            )
            await self._emit_mark_price(mark)
        except Exception:
            logger.exception("[BinanceOptionsDataFetcher] index parse error")
