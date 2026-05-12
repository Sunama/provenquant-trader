from __future__ import annotations

import uuid
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base
from app.core.enums import MarketType


class TradeHistory(Base):
    """
    Immutable record of every executed trade or balance-affecting event.
    Written by TradeExecuterProcess after each open/close; also used for
    external events (deposits, withdrawals) recorded by live adapters.
    """
    __tablename__ = "trade_history"

    id: Mapped[str] = mapped_column(
        sa.String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    strategy_id: Mapped[Optional[str]] = mapped_column(
        sa.String, sa.ForeignKey("strategy_configs.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    occurred_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, primary_key=True, index=True
    )
    # open_long | close_long | open_short | close_short |
    # transfer | withdraw | deposit
    trade_type: Mapped[str] = mapped_column(sa.String(30), nullable=False)

    symbol: Mapped[str] = mapped_column(sa.String(50), nullable=False, index=True)
    base_asset: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    quote_asset: Mapped[str] = mapped_column(sa.String(20), nullable=False)

    bought_asset: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    sold_asset: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    bought_qty: Mapped[float] = mapped_column(sa.Float, nullable=False)
    sold_qty: Mapped[float] = mapped_column(sa.Float, nullable=False)

    exchange_rate: Mapped[float] = mapped_column(sa.Float, nullable=False)
    fee: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0.0)
    fee_asset: Mapped[str] = mapped_column(sa.String(20), nullable=False, default="")

    exchange: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    market_type: Mapped[str] = mapped_column(sa.String(20), nullable=False)

    created_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )

    def __repr__(self) -> str:
        return f"<TradeHistory({self.trade_type} {self.symbol} @ {self.exchange_rate})>"
