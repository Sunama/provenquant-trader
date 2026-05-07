import sqlalchemy as sa
from app.db.base_class import Base
from sqlalchemy.orm import Mapped, mapped_column


class AggTrade(Base):
    __tablename__ = "agg_trades"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    asset_slug: Mapped[str] = mapped_column(sa.String(50), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    time: Mapped[sa.DateTime] = mapped_column(sa.DateTime(timezone=True), nullable=False, index=True)
    price: Mapped[float] = mapped_column(sa.Float, nullable=False)
    quantity: Mapped[float] = mapped_column(sa.Float, nullable=False)
    is_buyer_maker: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
