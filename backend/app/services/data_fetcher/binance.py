from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

import httpx
from websockets.asyncio.client import connect as ws_connect
from sqlalchemy.dialects.postgresql import insert

from app.db.models.tick import Tick
from app.db.session import SessionLocal
from app.services.data_fetcher import (
    AggTradeData,
    DataFetcher,
    FundingRateData,
    LiquidationData,
    MarkPriceData,
    OpenInterestData,
    OrderBookData,
    Subscription,
    TickData,
)

logger = logging.getLogger(__name__)

_TF_MAP = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m",
    "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d",
}

_OI_POLL_INTERVAL = 30
_RECONNECT_DELAY = 5

_FUTURES_WS_MAIN        = "wss://fstream.binance.com/stream"
_FUTURES_WS_TEST        = "wss://stream.binancefuture.com/stream"
_FUTURES_WS_SINGLE_MAIN = "wss://fstream.binance.com/ws"
_FUTURES_WS_SINGLE_TEST = "wss://stream.binancefuture.com/ws"
_FUTURES_REST_MAIN      = "https://fapi.binance.com"
_FUTURES_REST_TEST      = "https://testnet.binancefuture.com"


class BinanceBaseDataFetcher(DataFetcher):
    """
    Shared base for Binance market-type fetchers.

    Opens ONE combined WebSocket per fetcher instance that carries all stream
    types (kline, aggTrade, depth) for all subscribed symbols.  Subclasses
    inject additional streams via _extra_streams() and route extra message
    types by overriding _dispatch_stream_msg().
    """

    def __init__(self, testnet: bool = False) -> None:
        super().__init__()
        self._testnet = testnet
        self._tasks: dict[str, asyncio.Task] = {}
        self._kline_msg_count: int = 0

    # ── Subclass must supply these ────────────────────────────────

    @property
    def _ws_base(self) -> str:
        raise NotImplementedError

    @property
    def _rest_base(self) -> str:
        raise NotImplementedError

    @property
    def _klines_path(self) -> str:
        return "/fapi/v1/klines"

    # ── DataFetcher interface ─────────────────────────────────────

    async def _connect(self) -> None:
        pass  # tasks launched in _subscribe_symbols

    async def _disconnect(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    async def _subscribe_symbols(self, _subscriptions: list[Subscription]) -> None:
        await self._disconnect()
        self._launch_all_tasks()

    async def _unsubscribe_symbols(self, _subscriptions: list[Subscription]) -> None:
        await self._disconnect()
        if self._subscriptions:
            self._launch_all_tasks()

    # ── Task launcher ─────────────────────────────────────────────

    def _launch_all_tasks(self) -> None:
        if not self._subscriptions:
            return
        self._tasks["backfill"] = asyncio.create_task(self._backfill_task())
        self._tasks["stream"]   = asyncio.create_task(self._stream_task())

    # ── URL / stream helpers ──────────────────────────────────────

    def _symbols(self) -> list[str]:
        return list({s.asset_slug.lower() for s in self._subscriptions.values()})

    def _extra_streams(self) -> list[str]:
        return []

    def _all_streams_url(self) -> str | None:
        if not self._subscriptions:
            return None
        streams: list[str] = []
        for sub in self._subscriptions.values():
            streams.append(f"{sub.asset_slug.lower()}@kline_{_TF_MAP.get(sub.timeframe, '1m')}")
        for sym in self._symbols():
            streams.append(f"{sym}@aggTrade")
            streams.append(f"{sym}@depth20@100ms")
        streams.extend(self._extra_streams())
        return f"{self._ws_base}?streams={'/'.join(streams)}"

    # ── Combined stream task ──────────────────────────────────────

    async def _stream_task(self) -> None:
        while self._running:
            url = self._all_streams_url()
            if not url:
                await asyncio.sleep(1)
                continue
            try:
                async with ws_connect(url, ping_interval=20, ping_timeout=10) as ws:
                    logger.info(
                        f"[{self.__class__.__name__}] connected: "
                        f"{len(self._subscriptions)} subscriptions, "
                        f"symbols={self._symbols()}"
                    )
                    async for raw in ws:
                        if not self._running:
                            break
                        await self._dispatch_stream_msg(raw)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception(f"[{self.__class__.__name__}] stream error, reconnecting")
                await asyncio.sleep(_RECONNECT_DELAY)

    async def _dispatch_stream_msg(self, raw: str) -> None:
        try:
            stream = json.loads(raw).get("stream", "")
        except Exception:
            return
        if "@kline_" in stream:
            await self._handle_kline(raw)
        elif "@aggTrade" in stream:
            await self._handle_agg_trade(raw)
        elif "@depth" in stream:
            await self._handle_orderbook(raw)

    # ── Historical backfill ───────────────────────────────────────

    async def _backfill_task(self) -> None:
        seen: set[str] = set()
        async with httpx.AsyncClient(timeout=15) as client:
            for sub in list(self._subscriptions.values()):
                key = f"{sub.asset_slug}:{sub.timeframe}"
                if key in seen:
                    continue
                seen.add(key)
                interval = _TF_MAP.get(sub.timeframe, "1m")
                symbol = sub.asset_slug.upper()
                try:
                    resp = await client.get(
                        f"{self._rest_base}{self._klines_path}",
                        params={"symbol": symbol, "interval": interval, "limit": 200},
                    )
                    if resp.status_code != 200:
                        logger.warning(f"[backfill] {symbol} {interval} HTTP {resp.status_code}")
                        continue
                    rows = [
                        {
                            "asset_slug": sub.asset_slug.lower(),
                            "timeframe": sub.timeframe,
                            "time": datetime.fromtimestamp(int(k[0]) / 1000, tz=timezone.utc),
                            "open": float(k[1]),
                            "high": float(k[2]),
                            "low": float(k[3]),
                            "close": float(k[4]),
                            "volume": float(k[5]),
                        }
                        for k in resp.json()
                    ]
                    if rows:
                        async with SessionLocal() as db:
                            await db.execute(
                                insert(Tick).values(rows).on_conflict_do_nothing(constraint="uq_tick")
                            )
                            await db.commit()
                        logger.info(f"[backfill] {symbol} {interval}: seeded {len(rows)} bars")
                except asyncio.CancelledError:
                    return
                except Exception:
                    logger.exception(f"[backfill] {symbol} {interval} failed")

    # ── Stream handlers ───────────────────────────────────────────

    async def _handle_kline(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
            data = msg.get("data", msg)
            kline = data.get("k")
            if not kline:
                return
            self._kline_msg_count += 1
            if self._kline_msg_count % 500 == 0:
                logger.debug(f"[{self.__class__.__name__}] kline heartbeat: {self._kline_msg_count} messages")
            if not kline.get("x"):  # only closed bars
                return
            symbol = data.get("s", "").lower()
            tick = TickData(
                asset_slug=symbol,
                timeframe=kline.get("i", "1m"),
                time=int(kline["t"]),
                open=float(kline["o"]),
                high=float(kline["h"]),
                low=float(kline["l"]),
                close=float(kline["c"]),
                volume=float(kline["v"]),
            )
            logger.info(f"[bar] {tick.asset_slug} {tick.timeframe} close={tick.close:.4f} vol={tick.volume:.2f}")
            await self._emit(tick)
        except Exception:
            logger.exception(f"[{self.__class__.__name__}] kline parse error")

    async def _handle_agg_trade(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
            data = msg.get("data", msg)
            if data.get("e") != "aggTrade":
                return
            agg = AggTradeData(
                asset_slug=data.get("s", "").lower(),
                exchange="binance",
                time=int(data["T"]),
                price=float(data["p"]),
                quantity=float(data["q"]),
                is_buyer_maker=bool(data.get("m", False)),
            )
            await self._emit_agg_trade(agg)
        except Exception:
            logger.exception(f"[{self.__class__.__name__}] aggTrade parse error")

    async def _handle_orderbook(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
            data = msg.get("data", msg)
            stream_name = msg.get("stream", "")
            symbol = stream_name.split("@")[0].lower() if stream_name else data.get("s", "").lower()
            if not symbol:
                return
            book = OrderBookData(
                asset_slug=symbol,
                exchange="binance",
                time=int(data.get("T", time.time() * 1000)),
                bids=data.get("b", [])[:20],
                asks=data.get("a", [])[:20],
            )
            await self._emit_orderbook(book)
        except Exception:
            logger.exception(f"[{self.__class__.__name__}] depth parse error")

    # ── Open Interest REST polling ────────────────────────────────

    async def _open_interest_loop(self) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            while self._running:
                for symbol in self._symbols():
                    try:
                        resp = await client.get(
                            f"{self._rest_base}/fapi/v1/openInterest",
                            params={"symbol": symbol.upper()},
                        )
                        if resp.status_code == 200:
                            body = resp.json()
                            oi = OpenInterestData(
                                asset_slug=symbol,
                                exchange="binance",
                                time=int(body.get("time", time.time() * 1000)),
                                oi_contracts=float(body.get("openInterest", 0)),
                                oi_value=None,
                            )
                            await self._emit_open_interest(oi)
                    except asyncio.CancelledError:
                        return
                    except Exception:
                        logger.exception(f"[{self.__class__.__name__}] OI poll error for {symbol}")
                try:
                    await asyncio.sleep(_OI_POLL_INTERVAL)
                except asyncio.CancelledError:
                    break


class BinanceFuturesDataFetcher(BinanceBaseDataFetcher):
    """
    USDT-M Futures WebSocket streams.

    Adds markPrice (includes fundingRate) via the combined stream and
    forceOrder (liquidations) via a separate global stream.
    Testnet: stream.binancefuture.com / testnet.binancefuture.com
    Mainnet: fstream.binance.com     / fapi.binance.com
    """

    @property
    def _ws_base(self) -> str:
        return _FUTURES_WS_TEST if self._testnet else _FUTURES_WS_MAIN

    @property
    def _ws_single(self) -> str:
        return _FUTURES_WS_SINGLE_TEST if self._testnet else _FUTURES_WS_SINGLE_MAIN

    @property
    def _rest_base(self) -> str:
        return _FUTURES_REST_TEST if self._testnet else _FUTURES_REST_MAIN

    def _extra_streams(self) -> list[str]:
        return [f"{s}@markPrice@1s" for s in self._symbols()]

    async def _dispatch_stream_msg(self, raw: str) -> None:
        try:
            stream = json.loads(raw).get("stream", "")
        except Exception:
            return
        if "@markPrice" in stream:
            await self._handle_mark_price(raw)
        else:
            await super()._dispatch_stream_msg(raw)

    def _launch_all_tasks(self) -> None:
        if not self._subscriptions:
            return
        super()._launch_all_tasks()
        self._tasks["oi_loop"]     = asyncio.create_task(self._open_interest_loop())
        self._tasks["liquidation"] = asyncio.create_task(self._liquidation_task())

    async def _handle_mark_price(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
            data = msg.get("data", msg)
            if data.get("e") != "markPriceUpdate":
                return
            symbol = data.get("s", "").lower()
            ts = int(data.get("T", time.time() * 1000))
            mark = MarkPriceData(
                asset_slug=symbol,
                exchange="binance",
                market_type="futures",
                time=ts,
                price=float(data["p"]),
                index_price=float(data["i"]) if data.get("i") else None,
            )
            await self._emit_mark_price(mark)
            funding_str = data.get("r", "")
            if funding_str:
                funding = FundingRateData(
                    asset_slug=symbol,
                    exchange="binance",
                    time=ts,
                    rate=float(funding_str),
                    next_funding_time=int(data["T"]) if data.get("T") else None,
                )
                await self._emit_funding_rate(funding)
        except Exception:
            logger.exception(f"[{self.__class__.__name__}] mark_price parse error")

    async def _liquidation_task(self) -> None:
        url = f"{self._ws_single}/!forceOrder@arr"
        while self._running:
            subscribed_symbols = set(self._symbols())
            try:
                async with ws_connect(url, ping_interval=20, ping_timeout=10) as ws:
                    logger.info(f"[{self.__class__.__name__}] forceOrder stream connected")
                    async for raw in ws:
                        if not self._running:
                            break
                        await self._handle_liquidation(raw, subscribed_symbols)
                        subscribed_symbols = set(self._symbols())
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception(f"[{self.__class__.__name__}] liquidation error, reconnecting")
                await asyncio.sleep(_RECONNECT_DELAY)

    async def _handle_liquidation(self, raw: str, subscribed_symbols: set[str]) -> None:
        try:
            msg = json.loads(raw)
            data = msg.get("o", msg)
            symbol = data.get("s", "").lower()
            if subscribed_symbols and symbol not in subscribed_symbols:
                return
            side_raw = data.get("S", "")
            liq = LiquidationData(
                asset_slug=symbol,
                exchange="binance",
                time=int(data.get("T", time.time() * 1000)),
                side="short_liq" if side_raw == "BUY" else "long_liq",
                price=float(data["p"]),
                quantity=float(data["q"]),
            )
            await self._emit_liquidation(liq)
        except Exception:
            logger.exception(f"[{self.__class__.__name__}] liquidation parse error")
