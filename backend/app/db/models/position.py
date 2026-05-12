import sqlalchemy as sa
from app.db.base_class import Base
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional


class Position(Base):
    """
    Represents an open or closed paper-trade position.
    """
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    strategy_id: Mapped[str] = mapped_column(sa.String, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(sa.String, nullable=False)
    side: Mapped[str] = mapped_column(sa.String, nullable=False)  # "long" | "short"

    entry_price: Mapped[float] = mapped_column(sa.Float, nullable=False)
    entry_time: Mapped[sa.DateTime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    size: Mapped[float] = mapped_column(sa.Float, nullable=False)

    exit_price: Mapped[Optional[float]] = mapped_column(sa.Float, nullable=True)
    exit_time: Mapped[Optional[sa.DateTime]] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    exit_reason: Mapped[Optional[str]] = mapped_column(sa.String, nullable=True)  # "tp" | "sl" | "signal" | "manual"

    pnl: Mapped[Optional[float]] = mapped_column(sa.Float, nullable=True)
    pnl_pct: Mapped[Optional[float]] = mapped_column(sa.Float, nullable=True)

    is_open: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    leverage: Mapped[float] = mapped_column(sa.Float, nullable=False, default=1.0)

    created_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )

    def __repr__(self) -> str:
        return f"<Position(id={self.id}, strategy={self.strategy_id}, {self.side} {self.symbol})>"
