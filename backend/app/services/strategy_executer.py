from __future__ import annotations

import inspect
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import redis.asyncio as aioredis

from app.core.settings import settings
from app.services.data_fetcher import Subscription, TickData


class SignalAction(str, Enum):
    # Spot & Options
    BUY = "buy"
    SELL = "sell"
    # Futures
    OPEN_LONG = "open_long"
    CLOSE_LONG = "close_long"
    OPEN_SHORT = "open_short"
    CLOSE_SHORT = "close_short"


class PriceMethod(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


@dataclass
class TradeSignal:
    execute: SignalAction
    asset_num: int          # 0-based index into strategy's StrategyAsset list
    exchange_num: int       # 0-based index into strategy's ExchangeAccount list
    market_type: str        # spot | futures | options
    amount: float           # 0.0–1.0 fraction of available balance
    price_method: PriceMethod = PriceMethod.MARKET
    price: Optional[float] = None   # required when price_method=LIMIT
    tp_pct: Optional[float] = None
    sl_pct: Optional[float] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class ParameterSchema:
    name: str
    type: str               # bool|int|float|str
    default: Any
    min: Optional[float] = None
    max: Optional[float] = None
    description: str = ""


@dataclass
class StrategyAssetConfig:
    asset_num: int
    symbol: str
    exchange: str
    timeframe: str
    market_type: str
    tick_process: bool
    base_asset: str = ""
    quote_asset: str = ""


@dataclass
class IndicatorPoint:
    time: int   # unix ms — matches TickData convention
    value: float


@dataclass
class IndicatorSeries:
    name: str
    plot: str   # "on_chart" | "oscillator"
    color: str = "#2196f3"
    data: list[IndicatorPoint] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "plot": self.plot,
            "color": self.color,
            "data": [{"time": p.time, "value": p.value} for p in self.data],
        }


class StrategyExecuter(ABC):
    """
    Base class for all trading strategies.

    Subclasses must define:
      - id: unique string identifier (used for Redis race-condition locking)
      - parameter_schema: list of ParameterSchema describing configurable params
      - subscriptions: list of Subscription; set tick_process=True on the driving asset
      - execute(tick, asset_num): core logic — return list[TradeSignal] (empty = no trade)

    Instances are NOT long-lived; StrategyExecuterManager spawns a fresh instance per
    Celery task. Persistent state must live in Redis or Postgres.
    """

    def __init__(
        self,
        params: dict | None = None,
        assets: list[StrategyAssetConfig] | None = None,
        config_id: str = "",
    ) -> None:
        self.params: dict = params or {}
        self.assets: list[StrategyAssetConfig] = assets or []
        self.config_id: str = config_id   # DB StrategyConfig.id — used for Redis state keys

    @property
    @abstractmethod
    def id(self) -> str: ...

    @property
    @abstractmethod
    def parameter_schema(self) -> list[ParameterSchema]: ...

    @property
    @abstractmethod
    def subscriptions(self) -> list[Subscription]: ...

    @abstractmethod
    async def execute(self, tick: TickData, asset_num: int) -> list[TradeSignal]:
        """
        Process one closed bar and return a list of trade signals.
        asset_num identifies which subscribed asset triggered this call.
        Return an empty list to take no action.
        """
        ...

    def indicators(self, klines: list) -> list[IndicatorSeries]:
        """Override to return indicator series for chart display.
        klines = list[Tick] from InternalDataFetcher.
        """
        return []

    # ── Persistent state helpers (Redis) ─────────────────────────

    async def get_status(self) -> str:
        """Return current strategy status from Redis (default: 'neutral')."""
        async with aioredis.from_url(settings.REDIS_URL, decode_responses=True) as r:
            return await r.get(f"strategy:status:{self.config_id}") or "neutral"

    async def set_status(self, status: str) -> None:
        """Persist strategy status to Redis."""
        async with aioredis.from_url(settings.REDIS_URL, decode_responses=True) as r:
            await r.set(f"strategy:status:{self.config_id}", status)

    async def get_recent_closes(self, symbol: str, timeframe: str, limit: int) -> list[float]:
        """Fetch recent close prices from Redis tick buffer (newest first → reversed for chronological)."""
        async with aioredis.from_url(settings.REDIS_URL, decode_responses=True) as r:
            raw_list = await r.lrange(f"tick:{symbol}:{timeframe}", 0, limit - 1)
        closes: list[float] = []
        for raw in reversed(raw_list):
            try:
                closes.append(float(json.loads(raw)["close"]))
            except Exception:
                pass
        return closes

    @classmethod
    def _is_legacy(cls) -> bool:
        """Detect old-style execute(tick) -> TradeSignal | None signature for shim."""
        sig = inspect.signature(cls.execute)
        return "asset_num" not in sig.parameters
