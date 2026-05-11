import sqlalchemy as sa
from app.db.base_class import Base
from app.core.enums import MarketType
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.db.models.strategy_config import StrategyConfig


class StrategyAsset(Base):
    """
    One row per leg subscribed by a strategy.
    leg_num is the 0-based index used by LegOrder to reference this asset.
    role is a strategy-defined label (e.g. 'primary', 'hedge', 'anchor').
    tick_process=True means receiving a tick for this leg triggers strategy execution.
    """
    __tablename__ = "strategy_assets"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    strategy_id: Mapped[str] = mapped_column(
        sa.String, sa.ForeignKey("strategy_configs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    leg_num: Mapped[int] = mapped_column(sa.Integer, nullable=False)   # replaces asset_num
    role: Mapped[str] = mapped_column(sa.String(50), nullable=False, default="primary")
    symbol: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    exchange: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    timeframe: Mapped[str] = mapped_column(sa.String(10), nullable=False)
    market_type: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    tick_process: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    subscribe_depth: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    description: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    base_asset: Mapped[Optional[str]] = mapped_column(sa.String(20), nullable=True)
    quote_asset: Mapped[Optional[str]] = mapped_column(sa.String(20), nullable=True)
    exchange_account_num: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

    strategy: Mapped["StrategyConfig"] = relationship("StrategyConfig", back_populates="assets")

    def __repr__(self) -> str:
        return f"<StrategyAsset(strategy={self.strategy_id}, leg={self.leg_num}, role={self.role}, symbol={self.symbol})>"
