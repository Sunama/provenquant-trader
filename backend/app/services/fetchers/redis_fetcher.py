from __future__ import annotations

import json
import logging
from typing import Optional

import redis.asyncio as aioredis

from app.core.settings import settings
from app.services.data_fetcher import OrderBookData, TickData

logger = logging.getLogger(__name__)


class RedisDataFetcher:
    """
    Input type 2: Data that lives in Redis, updated by WebSocket streams.
    Provides recent tick history, order book snapshots, and strategy status.
    """

    def __init__(self, config_id: str) -> None:
        self._config_id = config_id

    async def get_recent_closes(self, symbol: str, timeframe: str, market_type: str = "futures", limit: int = 50) -> list[float]:
        """Fetch recent close prices from Redis tick buffer (chronological order)."""
        key = f"tick:{symbol}:{timeframe}:{market_type}"
        async with aioredis.from_url(settings.REDIS_URL, decode_responses=True) as r:
            raw_list = await r.lrange(key, 0, limit - 1)
        closes: list[float] = []
        for raw in reversed(raw_list):
            try:
                closes.append(float(json.loads(raw)["close"]))
            except Exception:
                pass
        return closes

    async def get_latest_tick(self, symbol: str, timeframe: str, market_type: str = "futures") -> Optional[TickData]:
        """Return the most recent closed bar from Redis."""
        key = f"tick:{symbol}:{timeframe}:{market_type}"
        async with aioredis.from_url(settings.REDIS_URL, decode_responses=True) as r:
            raw = await r.lindex(key, 0)
        if not raw:
            return None
        try:
            d = json.loads(raw)
            return TickData(**d)
        except Exception:
            return None

    async def get_orderbook(self, symbol: str, exchange: str = "binance", market_type: str = "futures") -> Optional[OrderBookData]:
        """Return latest order book snapshot from Redis."""
        key = f"orderbook:{symbol}:{exchange}:{market_type}"
        async with aioredis.from_url(settings.REDIS_URL, decode_responses=True) as r:
            raw = await r.get(key)
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return OrderBookData(
                symbol=symbol,
                exchange=exchange,
                time=data.get("time", 0),
                bids=data.get("bids", []),
                asks=data.get("asks", []),
                market_type=market_type,
            )
        except Exception:
            return None

    async def get_status(self) -> str:
        """Return current strategy status string from Redis (default: 'neutral')."""
        async with aioredis.from_url(settings.REDIS_URL, decode_responses=True) as r:
            return await r.get(f"strategy:status:{self._config_id}") or "neutral"

    async def set_status(self, status: str) -> None:
        """Persist strategy status string to Redis."""
        async with aioredis.from_url(settings.REDIS_URL, decode_responses=True) as r:
            await r.set(f"strategy:status:{self._config_id}", status)

    async def get_state(self, key: str, default: str = "") -> str:
        """Read an arbitrary strategy state value by key."""
        async with aioredis.from_url(settings.REDIS_URL, decode_responses=True) as r:
            return await r.get(f"strategy:state:{self._config_id}:{key}") or default

    async def set_state(self, key: str, value: str) -> None:
        """Write an arbitrary strategy state value by key."""
        async with aioredis.from_url(settings.REDIS_URL, decode_responses=True) as r:
            await r.set(f"strategy:state:{self._config_id}:{key}", value)

    async def get_option_mark(self, symbol: str) -> Optional[dict]:
        """
        Return the latest mark price + Greeks for an option symbol.

        Written by BinanceOptionsDataFetcher on every markPrice WebSocket message.
        Key: ``options:mark:{symbol}``

        Returns a dict with keys:
            mark_price, index_price, delta, gamma, theta, vega, iv,
            bid_iv, ask_iv, time
        or None if the symbol has no data yet.
        """
        key = f"options:mark:{symbol}"
        async with aioredis.from_url(settings.REDIS_URL, decode_responses=True) as r:
            raw = await r.get(key)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None
