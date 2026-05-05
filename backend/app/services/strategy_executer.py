from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app.services.data_fetcher import Subscription, TickData


class SignalSide(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass
class TradeSignal:
    side: SignalSide
    asset_slug: str
    timeframe: str
    price: float          # signal price (close of the bar that triggered it)
    tp_pct: float         # take-profit % (e.g. 0.02 = 2%)
    sl_pct: float         # stop-loss %
    size_pct: float = 1.0 # fraction of available balance to use


class StrategyExecuter(ABC):
    """
    Base class for all trading strategies.

    Subclasses must define:
      - id: unique string identifier (used for race-condition locking)
      - subscriptions: list of Subscription objects; mark the driving one is_trigger=True
      - execute(): core logic — return a TradeSignal or None

    Instances are NOT long-lived: StrategyExecuterManager spawns a fresh instance
    per Celery task invocation (stateless execution).  Persistent state must live
    in Redis or Postgres.
    """

    def __init__(self, params: dict | None = None) -> None:
        self.params: dict = params or {}

    @property
    @abstractmethod
    def id(self) -> str: ...

    @property
    @abstractmethod
    def subscriptions(self) -> list[Subscription]: ...

    @abstractmethod
    async def execute(self, tick: TickData) -> Optional[TradeSignal]:
        """Process one closed bar and return a signal or None."""
        ...
