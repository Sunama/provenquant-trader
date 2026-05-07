from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from app.services.data_fetcher import Subscription, TickData


class SignalSide(str, Enum):
    LONG = "long"
    SHORT = "short"
    BUY = "buy"
    SELL = "sell"
    CALL = "call"
    PUT = "put"


@dataclass
class TradeSignal:
    execute: SignalSide
    asset_num: int          # 0-based index into strategy's StrategyAsset list
    exchange_num: int       # 0-based index into strategy's ExchangeAccount list
    market_type: str        # spot|futures|options
    amount: float           # 0.0–1.0 fraction of available balance
    tp_pct: Optional[float] = None
    sl_pct: Optional[float] = None
    price: Optional[float] = None   # None = market order
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
    asset_slug: str
    exchange: str
    timeframe: str
    market_type: str
    tick_process: bool


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
    ) -> None:
        self.params: dict = params or {}
        self.assets: list[StrategyAssetConfig] = assets or []

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

    @classmethod
    def _is_legacy(cls) -> bool:
        """Detect old-style execute(tick) -> TradeSignal | None signature for shim."""
        sig = inspect.signature(cls.execute)
        return "asset_num" not in sig.parameters
