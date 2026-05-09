from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from app.services.strategy_executer import PriceMethod


@dataclass
class OrderResult:
    order_id: str
    symbol: str
    side: str       # "long" | "short"
    price: float
    size: float
    status: str     # "filled" | "pending" | "cancelled"


@dataclass
class PositionInfo:
    symbol: str
    side: str
    size: float
    entry_price: float
    unrealised_pnl: float
    unrealised_pnl_pct: float


@dataclass
class OrderRecord:
    order_id: str
    symbol: str
    side: str
    order_type: str     # "market" | "limit"
    price: float
    size: float
    status: str
    created_at: str
    filled_at: Optional[str] = None


class TradeAdapter(ABC):
    """
    Abstract interface between TradeExecuter and an exchange / paper engine.

    All methods are async so implementations can call external APIs without blocking.
    """

    @abstractmethod
    async def get_balance(self) -> float:
        """Return available quote-asset balance (e.g. USDT)."""
        ...

    @abstractmethod
    async def get_asset_balance(self, asset: str) -> float:
        """Return balance of a specific asset (e.g. 'BTC', 'USDT')."""
        ...

    @abstractmethod
    async def get_all_balances(self) -> dict[str, float]:
        """Return all non-zero asset balances as {asset: quantity}."""
        ...

    @abstractmethod
    async def open_position(
        self,
        symbol: str,
        side: str,
        size: float,
        price: float,
        tp_price: Optional[float] = None,
        sl_price: Optional[float] = None,
        price_method: PriceMethod = PriceMethod.MARKET,
    ) -> OrderResult:
        """Open a new position. Returns fill details (may be pending for limit orders)."""
        ...

    @abstractmethod
    async def close_position(
        self,
        symbol: str,
        side: str,
        price: float,
        reason: str = "signal",
    ) -> OrderResult:
        """Close an existing open position."""
        ...

    @abstractmethod
    async def get_open_position(self, symbol: str) -> Optional[PositionInfo]:
        """Return current open position for symbol, or None."""
        ...

    @abstractmethod
    async def get_order_history(self, symbol: str, limit: int = 50) -> list[OrderRecord]:
        """Return recent closed orders for symbol."""
        ...
