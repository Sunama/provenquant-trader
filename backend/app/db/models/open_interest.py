import sqlalchemy as sa
from app.db.base_class import Base
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional


class OpenInterest(Base):
    __tablename__ = "open_interest"
    __table_args__ = (
        sa.UniqueConstraint("symbol", "exchange", "time", name="uq_open_interest"),
    )

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(sa.String(50), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    time: Mapped[sa.DateTime] = mapped_column(sa.DateTime(timezone=True), nullable=False, index=True)
    oi_contracts: Mapped[float] = mapped_column(sa.Float, nullable=False)
    oi_value: Mapped[Optional[float]] = mapped_column(sa.Float, nullable=True)
