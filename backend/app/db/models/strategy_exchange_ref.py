import sqlalchemy as sa
from app.db.base_class import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.db.models.strategy_config import StrategyConfig
    from app.db.models.exchange_account import ExchangeAccount


class StrategyExchangeRef(Base):
    """
    Links a strategy to its exchange accounts in order.
    exchange_num is the 0-based index used by TradeSignal.exchange_num.
    """
    __tablename__ = "strategy_exchange_refs"
    __table_args__ = (
        sa.UniqueConstraint("strategy_id", "exchange_num", name="uq_strategy_exchange_num"),
    )

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    strategy_id: Mapped[str] = mapped_column(
        sa.String, sa.ForeignKey("strategy_configs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    exchange_account_id: Mapped[str] = mapped_column(
        sa.String, sa.ForeignKey("exchange_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    exchange_num: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)

    strategy: Mapped["StrategyConfig"] = relationship("StrategyConfig", back_populates="exchange_refs")
    exchange_account: Mapped["ExchangeAccount"] = relationship("ExchangeAccount", back_populates="strategy_refs")

    def __repr__(self) -> str:
        return f"<StrategyExchangeRef(strategy={self.strategy_id}, num={self.exchange_num})>"
