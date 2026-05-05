import sqlalchemy as sa
from app.db.base_class import Base
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional


class StrategyConfig(Base):
    """
    Persisted configuration for an active strategy instance.
    The strategy_class field is the importable dotted path (e.g. "strategies.mbml.MBMLStrategy").
    """
    __tablename__ = "strategy_configs"

    id: Mapped[str] = mapped_column(sa.String, primary_key=True)
    strategy_class: Mapped[str] = mapped_column(sa.String, nullable=False)
    asset_slug: Mapped[str] = mapped_column(sa.String, nullable=False)
    timeframe: Mapped[str] = mapped_column(sa.String, nullable=False)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    params: Mapped[Optional[dict]] = mapped_column(sa.JSON, nullable=True)
    created_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    updated_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )

    def __repr__(self) -> str:
        return f"<StrategyConfig(id={self.id}, asset={self.asset_slug}, tf={self.timeframe})>"
