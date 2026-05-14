from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, TYPE_CHECKING

from app.services.data_fetcher import Subscription

if TYPE_CHECKING:
    from app.services.strategy_context import StrategyContext


# ── Enums ─────────────────────────────────────────────────────────────────────


class SignalAction(str, Enum):
    OPEN_LONG = "open_long"
    CLOSE_LONG = "close_long"
    OPEN_SHORT = "open_short"
    CLOSE_SHORT = "close_short"


class PriceMethod(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class AmountMode(str, Enum):
    """Controls how LegOrder.amount is interpreted by TradeExecuterProcess."""
    PORTFOLIO_PCT_REALIZED = "portfolio_pct_realized"
    """Fraction of cash balance (realized). Default — equivalent to old TradeSignal."""
    PORTFOLIO_PCT_UNREALIZED = "portfolio_pct_unrealized"
    """Fraction of total portfolio value including open positions (unrealized)."""
    UNITS = "units"
    """Exact number of contracts or coins to trade."""
    RATIO_TO_LEG = "ratio_to_leg"
    """Ratio relative to an open position on reference_leg (hedging / pair trading)."""


# ── Data structures ────────────────────────────────────────────────────────────


@dataclass
class StrategyLeg:
    """
    Describes one instrument leg subscribed by a strategy.
    Replaces the old StrategyAssetConfig; adds role and exchange_account_num.
    """
    leg_num: int               # 0-based index matching StrategyAsset.leg_num in DB
    role: str                  # strategy-defined label, e.g. "primary", "hedge", "anchor"
    symbol: str
    exchange: str
    market_type: str
    timeframe: str
    tick_process: bool
    subscribe_depth: bool = False
    base_asset: str = ""
    quote_asset: str = ""
    exchange_account_num: int = 0   # links to StrategyExchangeRef.exchange_num
    transaction_fee: float = 0.0002  # fractional fee per trade (e.g. 0.0002 = 0.02%)


@dataclass
class ParameterSchema:
    name: str
    type: str               # bool | int | float | str
    default: Any
    min: Optional[float] = None
    max: Optional[float] = None
    description: str = ""


@dataclass
class LegOrder:
    """
    One trade instruction for a single leg inside an ExecutionPlan.

    amount semantics depend on amount_mode:
      PORTFOLIO_PCT_REALIZED   — 0.0–1.0 fraction of cash balance
      PORTFOLIO_PCT_UNREALIZED — 0.0–1.0 fraction of total portfolio value
      UNITS                    — absolute quantity (contracts / coins)
      RATIO_TO_LEG             — multiplier relative to reference_leg open position size
    """
    leg_num: int
    action: SignalAction
    amount: float
    amount_mode: AmountMode = AmountMode.PORTFOLIO_PCT_REALIZED
    reference_leg: Optional[int] = None    # required when amount_mode=RATIO_TO_LEG
    price_method: PriceMethod = PriceMethod.MARKET
    price: Optional[float] = None
    tp_pct: Optional[float] = None
    sl_pct: Optional[float] = None
    metadata: dict = field(default_factory=dict)
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "leg_num": self.leg_num,
            "action": self.action.value,
            "amount": self.amount,
            "amount_mode": self.amount_mode.value,
            "reference_leg": self.reference_leg,
            "price_method": self.price_method.value,
            "price": self.price,
            "tp_pct": self.tp_pct,
            "sl_pct": self.sl_pct,
            "metadata": self.metadata,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "LegOrder":
        return cls(
            leg_num=int(d["leg_num"]),
            action=SignalAction(d["action"]),
            amount=float(d["amount"]),
            amount_mode=AmountMode(d.get("amount_mode", AmountMode.PORTFOLIO_PCT_REALIZED.value)),
            reference_leg=int(d["reference_leg"]) if d.get("reference_leg") is not None else None,
            price_method=PriceMethod(d.get("price_method", PriceMethod.MARKET.value)),
            price=float(d["price"]) if d.get("price") is not None else None,
            tp_pct=float(d["tp_pct"]) if d.get("tp_pct") is not None else None,
            sl_pct=float(d["sl_pct"]) if d.get("sl_pct") is not None else None,
            metadata=d.get("metadata", {}),
            reason=d.get("reason") or None,
        )


@dataclass
class ExecutionPlan:
    """
    Return value of StrategyExecuter.execute().
    Contains one or more LegOrders and an optional post-execution callback key.

    on_complete: if set, TradeExecuterProcess publishes this key to 'executions:callbacks'
    stream after all orders execute. Useful for arbitrage settlement flows.
    """
    orders: list[LegOrder]
    on_complete: Optional[str] = None   # event key, e.g. "transfer_funds"
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "orders": [o.to_dict() for o in self.orders],
            "on_complete": self.on_complete,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ExecutionPlan":
        return cls(
            orders=[LegOrder.from_dict(o) for o in d["orders"]],
            on_complete=d.get("on_complete"),
            metadata=d.get("metadata", {}),
        )


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


# ── Abstract base ──────────────────────────────────────────────────────────────


class StrategyExecuter(ABC):
    """
    Base class for all trading strategies.

    Subclasses must implement:
      - id:               unique string identifier (used for Redis locks)
      - parameter_schema: list[ParameterSchema] describing configurable params
      - subscriptions:    list[Subscription]; set tick_process=True on driving legs
      - execute(context): core logic — return ExecutionPlan or None (no trade)

    Instances are NOT long-lived; a fresh instance is created per Celery task.
    All persistent state must live in Redis (via context.redis) or Postgres.
    """

    def __init__(
        self,
        params: dict | None = None,
        legs: list[StrategyLeg] | None = None,
        config_id: str = "",
    ) -> None:
        self.params: dict = params or {}
        self.legs: list[StrategyLeg] = legs or []
        self.config_id: str = config_id

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
    async def execute(self, context: "StrategyContext") -> Optional[ExecutionPlan]:
        """
        Process one closed bar and return an ExecutionPlan or None.
        All market data access goes through context.redis / context.db / context.pq.
        """
        ...

    def indicators(self, klines: list) -> list[IndicatorSeries]:
        """Override to return indicator series for chart display."""
        return []
