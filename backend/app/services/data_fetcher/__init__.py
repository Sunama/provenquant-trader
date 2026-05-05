from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Awaitable

import redis.asyncio as aioredis

from app.core.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class Subscription:
    asset_slug: str
    timeframe: str
    exchange: str = "binance"
    is_trigger: bool = False


@dataclass
class TickData:
    asset_slug: str
    timeframe: str
    time: int          # Unix ms
    open: float
    high: float
    low: float
    close: float
    volume: float

    def redis_key(self) -> str:
        return f"tick:{self.asset_slug}:{self.timeframe}"

    def to_dict(self) -> dict:
        return {
            "asset_slug": self.asset_slug,
            "timeframe": self.timeframe,
            "time": self.time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


TickCallback = Callable[[TickData], Awaitable[None]]


class DataFetcher(ABC):
    """
    Base class for real-time market data fetching.

    Subclasses implement _connect() / _disconnect() / _subscribe_symbols() /
    _unsubscribe_symbols() using exchange-specific WebSocket libraries.

    On each closed bar the subclass calls self._emit(tick) which:
      1. Stores the tick in Redis (LPUSH, capped list)
      2. Invokes all registered on_tick callbacks
    """

    REDIS_TICK_MAXLEN = 1440  # keep 1 day of 1m bars in Redis

    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None
        self._subscriptions: dict[str, Subscription] = {}  # key → Subscription
        self._callbacks: list[TickCallback] = []
        self._running = False

    # ── Public API ────────────────────────────────────────────────

    def add_callback(self, cb: TickCallback) -> None:
        self._callbacks.append(cb)

    def set_subscriptions(self, subscriptions: list[Subscription]) -> None:
        """Replace the full subscription set (called by StrategyExecuterManager)."""
        new = {f"{s.asset_slug}:{s.timeframe}": s for s in subscriptions}
        added = set(new) - set(self._subscriptions)
        removed = set(self._subscriptions) - set(new)

        self._subscriptions = new

        if self._running:
            if added:
                asyncio.create_task(
                    self._subscribe_symbols([new[k] for k in added])
                )
            if removed:
                asyncio.create_task(
                    self._unsubscribe_symbols([self._subscriptions[k] for k in removed if k in self._subscriptions])
                )

    async def start(self) -> None:
        self._redis = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        self._running = True
        await self._connect()
        if self._subscriptions:
            await self._subscribe_symbols(list(self._subscriptions.values()))
        logger.info(f"{self.__class__.__name__} started")

    async def stop(self) -> None:
        self._running = False
        await self._disconnect()
        if self._redis:
            await self._redis.aclose()
        logger.info(f"{self.__class__.__name__} stopped")

    # ── Internal helpers ─────────────────────────────────────────

    async def _emit(self, tick: TickData) -> None:
        if self._redis:
            key = tick.redis_key()
            await self._redis.lpush(key, json.dumps(tick.to_dict()))
            await self._redis.ltrim(key, 0, self.REDIS_TICK_MAXLEN - 1)

        for cb in self._callbacks:
            try:
                await cb(tick)
            except Exception:
                logger.exception("Tick callback raised")

    # ── Abstract interface ────────────────────────────────────────

    @abstractmethod
    async def _connect(self) -> None: ...

    @abstractmethod
    async def _disconnect(self) -> None: ...

    @abstractmethod
    async def _subscribe_symbols(self, subscriptions: list[Subscription]) -> None: ...

    @abstractmethod
    async def _unsubscribe_symbols(self, subscriptions: list[Subscription]) -> None: ...
