from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class OrderResult:
    order_id: str
    asset_slug: str
    side: str       # "long" | "short"
    price: float
    size: float
    status: str     # "filled" | "pending" | "cancelled"


@dataclass
class PositionInfo:
    asset_slug: str
    side: str
    size: float
    entry_price: float
    unrealised_pnl: float
    unrealised_pnl_pct: float


class TradeAdapter(ABC):
    """
    Abstract interface between TradeExecuter and an exchange / paper engine.

    All methods are async so implementations can call external APIs without blocking.
    """

    @abstractmethod
    async def get_balance(self) -> float:
        """Return available USDT balance."""
        ...

    @abstractmethod
    async def open_position(
        self,
        asset_slug: str,
        side: str,
        size: float,
        price: float,
        tp_price: Optional[float] = None,
        sl_price: Optional[float] = None,
    ) -> OrderResult:
        """Open a new position. Returns fill details."""
        ...

    @abstractmethod
    async def close_position(
        self,
        asset_slug: str,
        side: str,
        price: float,
        reason: str = "signal",
    ) -> OrderResult:
        """Close an existing open position."""
        ...

    @abstractmethod
    async def get_open_position(self, asset_slug: str) -> Optional[PositionInfo]:
        """Return current open position for asset_slug, or None."""
        ...
