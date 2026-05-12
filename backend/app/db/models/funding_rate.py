import sqlalchemy as sa
from app.db.base_class import Base
from app.core.enums import MarketType
from sqlalchemy.orm import Mapped, mapped_column


class FundingRate(Base):
    __tablename__ = "funding_rates"
    __table_args__ = (
        sa.UniqueConstraint("symbol", "exchange", "market_type", "time", name="uq_funding_rate"),
    )

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(sa.String(50), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    market_type: Mapped[str] = mapped_column(sa.String(20), nullable=False, default=MarketType.FUTURES.value)
    time: Mapped[sa.DateTime] = mapped_column(sa.DateTime(timezone=True), nullable=False, primary_key=True, index=True)
    rate: Mapped[float] = mapped_column(sa.Float, nullable=False)
