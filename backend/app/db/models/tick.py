import sqlalchemy as sa
from app.db.base_class import Base
from app.core.enums import MarketType
from sqlalchemy.orm import Mapped, mapped_column


class Tick(Base):
    """
    OHLCV tick flushed from Redis by DataCollector every minute.
    Indexed on (symbol, timeframe, market_type, time) for time-series queries.
    """
    __tablename__ = "ticks"
    __table_args__ = (
        sa.UniqueConstraint("symbol", "timeframe", "market_type", "time", name="uq_tick"),
    )

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(sa.String, nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(sa.String, nullable=False)
    market_type: Mapped[str] = mapped_column(sa.String(20), nullable=False, index=True)
    time: Mapped[sa.DateTime] = mapped_column(sa.DateTime(timezone=True), nullable=False, primary_key=True, index=True)

    open: Mapped[float] = mapped_column(sa.Float, nullable=False)
    high: Mapped[float] = mapped_column(sa.Float, nullable=False)
    low: Mapped[float] = mapped_column(sa.Float, nullable=False)
    close: Mapped[float] = mapped_column(sa.Float, nullable=False)
    volume: Mapped[float] = mapped_column(sa.Float, nullable=False)

    def __repr__(self) -> str:
        return f"<Tick({self.symbol} {self.timeframe} {self.market_type} {self.time})>"
