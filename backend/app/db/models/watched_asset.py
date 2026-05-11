from typing import Optional

import sqlalchemy as sa
from app.db.base_class import Base
from app.core.enums import MarketType
from sqlalchemy.orm import Mapped, mapped_column


class WatchedAsset(Base):
    """
    Assets to collect market data for, independent of active strategies.
    Used to build historical datasets for backtesting and optimization.
    """
    __tablename__ = "watched_assets"
    __table_args__ = (
        sa.UniqueConstraint("symbol", "exchange", "market_type", name="uq_watched_asset"),
    )

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(sa.String(50), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    market_type: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    timeframes: Mapped[list] = mapped_column(sa.JSON, nullable=False)
    base_asset: Mapped[Optional[str]] = mapped_column(sa.String(20), nullable=True)
    quote_asset: Mapped[Optional[str]] = mapped_column(sa.String(20), nullable=True)

    def __repr__(self) -> str:
        return f"<WatchedAsset(symbol={self.symbol}, exchange={self.exchange}, market_type={self.market_type})>"
