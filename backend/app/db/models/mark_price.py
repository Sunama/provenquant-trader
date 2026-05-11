import sqlalchemy as sa
from app.db.base_class import Base
from app.core.enums import MarketType
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional


class MarkPrice(Base):
    __tablename__ = "mark_prices"
    __table_args__ = (
        sa.UniqueConstraint("symbol", "exchange", "market_type", "time", name="uq_mark_price"),
    )

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(sa.String(50), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    market_type: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    time: Mapped[sa.DateTime] = mapped_column(sa.DateTime(timezone=True), nullable=False, index=True)
    price: Mapped[float] = mapped_column(sa.Float, nullable=False)
    index_price: Mapped[Optional[float]] = mapped_column(sa.Float, nullable=True)
