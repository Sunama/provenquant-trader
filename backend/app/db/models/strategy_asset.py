import sqlalchemy as sa
from app.db.base_class import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.db.models.strategy_config import StrategyConfig


class StrategyAsset(Base):
    """
    One row per asset subscribed by a strategy.
    asset_num is the 0-based index used by TradeSignal to reference this asset.
    tick_process=True means receiving a tick for this asset triggers strategy execution.
    """
    __tablename__ = "strategy_assets"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    strategy_id: Mapped[str] = mapped_column(
        sa.String, sa.ForeignKey("strategy_configs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    asset_num: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    symbol: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    exchange: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    timeframe: Mapped[str] = mapped_column(sa.String(10), nullable=False)
    market_type: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    tick_process: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    description: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    base_asset: Mapped[Optional[str]] = mapped_column(sa.String(20), nullable=True)
    quote_asset: Mapped[Optional[str]] = mapped_column(sa.String(20), nullable=True)

    strategy: Mapped["StrategyConfig"] = relationship("StrategyConfig", back_populates="assets")

    def __repr__(self) -> str:
        return f"<StrategyAsset(strategy={self.strategy_id}, num={self.asset_num}, symbol={self.symbol})>"
