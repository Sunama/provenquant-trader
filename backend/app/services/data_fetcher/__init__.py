from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Awaitable, Optional

import redis.asyncio as aioredis

from app.core.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class Subscription:
    asset_slug: str
    timeframe: str
    exchange: str = "binance"
    market_type: str = "futures"
    tick_process: bool = False      # True = receiving this tick triggers strategy execution
    description: str = ""           # human-readable role of this asset in the strategy


@dataclass
class TickData:
    asset_slug: str
    timeframe: str
    time: int           # Unix ms
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


@dataclass
class FundingRateData:
    asset_slug: str
    exchange: str
    time: int           # Unix ms
    rate: float
    next_funding_time: Optional[int] = None

    def redis_key(self) -> str:
        return f"funding:{self.asset_slug}:{self.exchange}"

    def to_dict(self) -> dict:
        return {
            "asset_slug": self.asset_slug,
            "exchange": self.exchange,
            "time": self.time,
            "rate": self.rate,
        }


@dataclass
class MarkPriceData:
    asset_slug: str
    exchange: str
    market_type: str
    time: int           # Unix ms
    price: float
    index_price: Optional[float] = None

    def redis_key(self) -> str:
        return f"mark_price:{self.asset_slug}:{self.exchange}:{self.market_type}"

    def to_dict(self) -> dict:
        return {
            "asset_slug": self.asset_slug,
            "exchange": self.exchange,
            "market_type": self.market_type,
            "time": self.time,
            "price": self.price,
            "index_price": self.index_price,
        }


@dataclass
class OpenInterestData:
    asset_slug: str
    exchange: str
    time: int           # Unix ms
    oi_contracts: float
    oi_value: Optional[float] = None

    def redis_key(self) -> str:
        return f"oi:{self.asset_slug}:{self.exchange}"

    def to_dict(self) -> dict:
        return {
            "asset_slug": self.asset_slug,
            "exchange": self.exchange,
            "time": self.time,
            "oi_contracts": self.oi_contracts,
            "oi_value": self.oi_value,
        }


@dataclass
class LiquidationData:
    asset_slug: str
    exchange: str
    time: int           # Unix ms
    side: str           # "long_liq"|"short_liq"
    price: float
    quantity: float

    def to_dict(self) -> dict:
        return {
            "asset_slug": self.asset_slug,
            "exchange": self.exchange,
            "time": self.time,
            "side": self.side,
            "price": self.price,
            "quantity": self.quantity,
        }


@dataclass
class AggTradeData:
    asset_slug: str
    exchange: str
    time: int           # Unix ms
    price: float
    quantity: float
    is_buyer_maker: bool

    def to_dict(self) -> dict:
        return {
            "asset_slug": self.asset_slug,
            "exchange": self.exchange,
            "time": self.time,
            "price": self.price,
            "quantity": self.quantity,
            "is_buyer_maker": int(self.is_buyer_maker),
        }


@dataclass
class OrderBookData:
    asset_slug: str
    exchange: str
    time: int           # Unix ms
    bids: list          # [[price, qty], ...]
    asks: list          # [[price, qty], ...]

    def redis_key(self) -> str:
        return f"orderbook:{self.asset_slug}:{self.exchange}"


TickCallback = Callable[[TickData], Awaitable[None]]
FundingRateCallback = Callable[[FundingRateData], Awaitable[None]]
MarkPriceCallback = Callable[[MarkPriceData], Awaitable[None]]
OpenInterestCallback = Callable[[OpenInterestData], Awaitable[None]]
LiquidationCallback = Callable[[LiquidationData], Awaitable[None]]
AggTradeCallback = Callable[[AggTradeData], Awaitable[None]]


class DataFetcher(ABC):
    """
    Base class for real-time market data fetching.

    Subclasses implement _connect() / _disconnect() / _subscribe_symbols() /
    _unsubscribe_symbols() using exchange-specific WebSocket libraries.

    On each closed bar the subclass calls self._emit(tick) which:
      1. Stores the tick in Redis (LPUSH, capped list) and publishes to ticks:broadcast
      2. Invokes all registered on_tick callbacks
    """

    REDIS_TICK_MAXLEN = 1440            # keep 1 day of 1m bars in Redis
    REDIS_MARK_PRICE_MAXLEN = 3600      # 1h of 1s mark price updates
    REDIS_OI_MAXLEN = 288               # 1 day of 5m OI snapshots

    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None
        self._subscriptions: dict[str, Subscription] = {}   # key → Subscription
        self._tick_callbacks: list[TickCallback] = []
        self._funding_callbacks: list[FundingRateCallback] = []
        self._mark_price_callbacks: list[MarkPriceCallback] = []
        self._oi_callbacks: list[OpenInterestCallback] = []
        self._liquidation_callbacks: list[LiquidationCallback] = []
        self._agg_trade_callbacks: list[AggTradeCallback] = []
        self._running = False

    # ── Public API ────────────────────────────────────────────────

    def add_callback(self, cb: TickCallback) -> None:
        self._tick_callbacks.append(cb)

    def add_funding_callback(self, cb: FundingRateCallback) -> None:
        self._funding_callbacks.append(cb)

    def add_mark_price_callback(self, cb: MarkPriceCallback) -> None:
        self._mark_price_callbacks.append(cb)

    def add_oi_callback(self, cb: OpenInterestCallback) -> None:
        self._oi_callbacks.append(cb)

    def add_liquidation_callback(self, cb: LiquidationCallback) -> None:
        self._liquidation_callbacks.append(cb)

    def add_agg_trade_callback(self, cb: AggTradeCallback) -> None:
        self._agg_trade_callbacks.append(cb)

    def set_subscriptions(self, subscriptions: list[Subscription]) -> None:
        """Replace the full subscription set (called by StrategyExecuterManager)."""
        new = {f"{s.asset_slug}:{s.timeframe}:{s.market_type}": s for s in subscriptions}
        added = set(new) - set(self._subscriptions)
        removed = set(self._subscriptions) - set(new)

        self._subscriptions = new

        if self._running:
            if added:
                asyncio.create_task(
                    self._subscribe_symbols([new[k] for k in added])
                )
            if removed:
                old_subs = {f"{s.asset_slug}:{s.timeframe}:{s.market_type}": s
                            for s in self._subscriptions.values()}
                asyncio.create_task(
                    self._unsubscribe_symbols([old_subs[k] for k in removed if k in old_subs])
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

    # ── Internal emit helpers ─────────────────────────────────────

    async def _emit(self, tick: TickData) -> None:
        if self._redis:
            key = tick.redis_key()
            payload = json.dumps(tick.to_dict())
            await self._redis.lpush(key, payload)
            await self._redis.ltrim(key, 0, self.REDIS_TICK_MAXLEN - 1)
            # Publish for WebSocket relay (zero-latency, fire-and-forget)
            await self._redis.publish("ticks:broadcast", payload)

        for cb in self._tick_callbacks:
            try:
                await cb(tick)
            except Exception:
                logger.exception("Tick callback raised")

    async def _emit_funding_rate(self, data: FundingRateData) -> None:
        if self._redis:
            key = data.redis_key()
            await self._redis.set(key, json.dumps(data.to_dict()))

        for cb in self._funding_callbacks:
            try:
                await cb(data)
            except Exception:
                logger.exception("FundingRate callback raised")

    async def _emit_mark_price(self, data: MarkPriceData) -> None:
        if self._redis:
            key = data.redis_key()
            await self._redis.lpush(key, json.dumps(data.to_dict()))
            await self._redis.ltrim(key, 0, self.REDIS_MARK_PRICE_MAXLEN - 1)

        for cb in self._mark_price_callbacks:
            try:
                await cb(data)
            except Exception:
                logger.exception("MarkPrice callback raised")

    async def _emit_open_interest(self, data: OpenInterestData) -> None:
        if self._redis:
            key = data.redis_key()
            await self._redis.lpush(key, json.dumps(data.to_dict()))
            await self._redis.ltrim(key, 0, self.REDIS_OI_MAXLEN - 1)

        for cb in self._oi_callbacks:
            try:
                await cb(data)
            except Exception:
                logger.exception("OpenInterest callback raised")

    async def _emit_liquidation(self, data: LiquidationData) -> None:
        if self._redis:
            # Use Redis Stream for liquidations (high-volume, need ack)
            await self._redis.xadd("liquidations:buffer", data.to_dict(), maxlen=50000)

        for cb in self._liquidation_callbacks:
            try:
                await cb(data)
            except Exception:
                logger.exception("Liquidation callback raised")

    async def _emit_agg_trade(self, data: AggTradeData) -> None:
        if self._redis:
            await self._redis.xadd("agg_trades:buffer", data.to_dict(), maxlen=100000)

        for cb in self._agg_trade_callbacks:
            try:
                await cb(data)
            except Exception:
                logger.exception("AggTrade callback raised")

    async def _emit_orderbook(self, data: OrderBookData) -> None:
        """Order book is Redis-only — snapshot, never persisted to Postgres."""
        if self._redis:
            await self._redis.set(
                data.redis_key(),
                json.dumps({"time": data.time, "bids": data.bids, "asks": data.asks}),
            )

    # ── Abstract interface ────────────────────────────────────────

    @abstractmethod
    async def _connect(self) -> None: ...

    @abstractmethod
    async def _disconnect(self) -> None: ...

    @abstractmethod
    async def _subscribe_symbols(self, subscriptions: list[Subscription]) -> None: ...

    @abstractmethod
    async def _unsubscribe_symbols(self, subscriptions: list[Subscription]) -> None: ...
