import sqlalchemy as sa
from app.db.base_class import Base
from sqlalchemy.orm import Mapped, mapped_column


class Tick(Base):
    """
    OHLCV tick flushed from Redis by DataCollector every minute.
    Indexed on (asset_slug, timeframe, time) for time-series queries.
    """
    __tablename__ = "ticks"
    __table_args__ = (
        sa.UniqueConstraint("asset_slug", "timeframe", "time", name="uq_tick"),
    )

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    asset_slug: Mapped[str] = mapped_column(sa.String, nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(sa.String, nullable=False)
    time: Mapped[sa.DateTime] = mapped_column(sa.DateTime(timezone=True), nullable=False, index=True)

    open: Mapped[float] = mapped_column(sa.Float, nullable=False)
    high: Mapped[float] = mapped_column(sa.Float, nullable=False)
    low: Mapped[float] = mapped_column(sa.Float, nullable=False)
    close: Mapped[float] = mapped_column(sa.Float, nullable=False)
    volume: Mapped[float] = mapped_column(sa.Float, nullable=False)

    def __repr__(self) -> str:
        return f"<Tick({self.asset_slug} {self.timeframe} {self.time})>"
