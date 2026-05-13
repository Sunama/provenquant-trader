from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx
import redis.asyncio as aioredis
from websockets.asyncio.client import connect as ws_connect

from app.core.settings import settings
from app.services.data_fetcher import (
    DataFetcher,
    MarkPriceData,
    OpenInterestData,
    Subscription,
    TickData,
)

logger = logging.getLogger(__name__)

_WS_BASE = "wss://nbstream.binance.com/eoptions/stream"
_EAPI_BASE = "https://eapi.binance.com/eapi/v1"
_RECONNECT_DELAY = 5

# 1 Binance EAPI contract = 0.01 BTC
CONTRACT_SIZE: float = 0.01


@dataclass
class OptionInfo:
    """Static metadata for a single Binance EAPI option contract."""
    symbol: str       # e.g. "BTC-250515-95000-C"
    side: str         # "CALL" or "PUT"
    strike: float
    expiry_ms: int    # Unix timestamp ms
    dte: float        # days to expiry at time of fetch


@dataclass
class OptionMark:
    """Live mark price + Greeks for an option symbol (from REST or WebSocket)."""
    symbol: str
    mark_price: float
    delta: float      # +0.0 to +1.0 for calls; -1.0 to 0.0 for puts
    gamma: float      # always positive; highest at ATM
    theta: float      # daily time decay (negative)
    vega: float       # sensitivity to 1% IV change
    iv: float         # implied volatility
    bid_iv: float = 0.0
    ask_iv: float = 0.0


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
        return list({s.symbol.upper() for s in self._subscriptions.values()})

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
                # Use event time (E) or fallback; "t" may be transaction time or theta
                ts = int(item.get("E") or item.get("t") or time.time() * 1000)
                mp = float(item["mp"]) if item.get("mp") else 0.0
                ip = float(item["ip"]) if item.get("ip") else None

                # Greeks — Binance EAPI WebSocket stream uses short keys:
                #   d=delta, g=gamma, t=theta (may conflict w/ tx-time), v=vega, vo=IV
                # Full-word names are used in the REST response; try both to be robust.
                delta = _parse_greek(item, "delta", "d")
                gamma = _parse_greek(item, "gamma", "g")
                # Skip "t" for theta fallback to avoid timestamp collision;
                # rely on the full word "theta" from the stream.
                theta = _parse_greek(item, "theta", None)
                vega  = _parse_greek(item, "vega",  "v")
                iv    = _parse_greek(item, "vo",    None)

                mark = MarkPriceData(
                    symbol=symbol,
                    exchange="binance_options",
                    market_type="options",
                    time=ts,
                    price=mp,
                    index_price=ip,
                )
                await self._emit_mark_price(mark)

                # Persist full mark + Greeks to Redis so strategies can read them
                if symbol:
                    await _write_option_mark_redis(
                        symbol=symbol,
                        mark_price=mp,
                        index_price=ip or 0.0,
                        delta=delta,
                        gamma=gamma,
                        theta=theta,
                        vega=vega,
                        iv=iv,
                        bid_iv=float(item.get("biv") or 0),
                        ask_iv=float(item.get("aiv") or 0),
                        ts=ts,
                    )

                # Emit as pseudo-tick for strategy consumption (close = mark price)
                if mp:
                    tick = TickData(
                        symbol=symbol,
                        timeframe="1s",
                        time=ts,
                        open=mp,
                        high=mp,
                        low=mp,
                        close=mp,
                        volume=0.0,
                        is_closed=True,
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
            ts = int(data.get("E") or data.get("t") or time.time() * 1000)
            price = float(data.get("p", 0.0))

            mark = MarkPriceData(
                symbol=f"{underlying}usdt",
                exchange="binance_options",
                market_type="options_index",
                time=ts,
                price=price,
                index_price=price,
            )
            await self._emit_mark_price(mark)
        except Exception:
            logger.exception("[BinanceOptionsDataFetcher] index parse error")

    # ── Static REST helpers (for one-time option chain lookup at strategy entry) ─

    @staticmethod
    async def fetch_option_chain(
        underlying: str = "BTCUSDT",
        spot_price: float = 0.0,
        target_dte: int = 7,
        min_dte: float = 1.0,
        timeout: float = 10.0,
    ) -> tuple[Optional[OptionInfo], Optional[OptionInfo]]:
        """
        One-shot REST lookup: find ATM call + put for the expiry nearest to
        *target_dte* days.  Returns (call_info, put_info) or (None, None).

        This is intentionally a static method — it does not touch the WebSocket
        connection at all, so it can be called from a strategy without side-effects.
        """
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{_EAPI_BASE}/optionInfo")
            resp.raise_for_status()
            items = resp.json()

        infos: list[OptionInfo] = []
        for item in items:
            if item.get("underlying") != underlying:
                continue
            expiry_ms = int(item["expiryDate"])
            dte = (expiry_ms - now_ms) / (1000 * 86400)
            if dte < min_dte:
                continue
            infos.append(OptionInfo(
                symbol=item["symbol"],
                side=item["side"],
                strike=float(item["strikePrice"]),
                expiry_ms=expiry_ms,
                dte=dte,
            ))

        if not infos:
            return None, None

        # Expiry with DTE nearest to target
        eligible = sorted(set(i.expiry_ms for i in infos))
        target_expiry = min(eligible, key=lambda e: abs((e - now_ms) / (1000 * 86400) - target_dte))
        expiry_infos = [i for i in infos if i.expiry_ms == target_expiry]

        # Strike nearest to spot
        strikes = sorted(set(i.strike for i in expiry_infos))
        if not strikes:
            return None, None
        atm_strike = min(strikes, key=lambda s: abs(s - spot_price)) if spot_price else strikes[len(strikes) // 2]

        call = next((i for i in expiry_infos if i.strike == atm_strike and i.side == "CALL"), None)
        put  = next((i for i in expiry_infos if i.strike == atm_strike and i.side == "PUT"),  None)

        if call and put:
            logger.info(
                f"[BinanceOptionsDataFetcher] ATM straddle: strike={atm_strike} "
                f"dte={call.dte:.1f}d call={call.symbol} put={put.symbol}"
            )
        return call, put

    @staticmethod
    async def fetch_option_mark_rest(symbol: str, timeout: float = 10.0) -> Optional[OptionMark]:
        """
        Fetch mark price + Greeks for a single option symbol via REST.
        Use at strategy entry when the WebSocket subscription may not yet have data.
        """
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{_EAPI_BASE}/mark", params={"symbol": symbol})
            resp.raise_for_status()
            data = resp.json()

        items = data if isinstance(data, list) else [data]
        for item in items:
            if item.get("symbol") == symbol:
                return OptionMark(
                    symbol=symbol,
                    mark_price=float(item["markPrice"]),
                    delta=float(item.get("delta") or 0),
                    gamma=float(item.get("gamma") or 0),
                    theta=float(item.get("theta") or 0),
                    vega=float(item.get("vega") or 0),
                    iv=float(item.get("markIV") or item.get("vo") or 0),
                    bid_iv=float(item.get("bidIV") or 0),
                    ask_iv=float(item.get("askIV") or 0),
                )
        return None


# ── Module-level helpers ──────────────────────────────────────────────────────

def _parse_greek(item: dict, full: str, short: Optional[str]) -> float:
    """Try full field name then abbreviated form; return 0.0 if absent."""
    v = item.get(full)
    if v is None and short:
        v = item.get(short)
    if v is None:
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


async def _write_option_mark_redis(
    symbol: str,
    mark_price: float,
    index_price: float,
    delta: float,
    gamma: float,
    theta: float,
    vega: float,
    iv: float,
    bid_iv: float,
    ask_iv: float,
    ts: int,
    ttl: int = 120,
) -> None:
    """Write option mark + Greeks to Redis key ``options:mark:{symbol}`` (TTL 2 min)."""
    from app.core.settings import settings  # local import to avoid circular
    payload = json.dumps({
        "symbol":      symbol,
        "mark_price":  mark_price,
        "index_price": index_price,
        "delta":       delta,
        "gamma":       gamma,
        "theta":       theta,
        "vega":        vega,
        "iv":          iv,
        "bid_iv":      bid_iv,
        "ask_iv":      ask_iv,
        "time":        ts,
    })
    try:
        async with aioredis.from_url(settings.REDIS_URL, decode_responses=True) as r:
            await r.set(f"options:mark:{symbol}", payload, ex=ttl)
    except Exception:
        logger.debug(f"[BinanceOptionsDataFetcher] Redis write failed for {symbol}")
