import uuid

import sqlalchemy as sa
from app.db.base_class import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.db.models.strategy_asset import StrategyAsset
    from app.db.models.strategy_exchange_ref import StrategyExchangeRef


class StrategyConfig(Base):
    """
    Persisted configuration for an active strategy instance.
    id is a UUID generated automatically — users identify strategies by name.
    Assets and exchange accounts are stored in related tables (strategy_assets, strategy_exchange_refs).
    """
    __tablename__ = "strategy_configs"

    id: Mapped[str] = mapped_column(
        sa.String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(sa.String(200), nullable=False, unique=True)
    strategy_class: Mapped[str] = mapped_column(sa.String, nullable=False)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    is_paper: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default="true")
    description: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    params: Mapped[Optional[dict]] = mapped_column(sa.JSON, nullable=True)
    parameters_schema: Mapped[Optional[list]] = mapped_column(sa.JSON, nullable=True)
    signal_definitions: Mapped[Optional[list]] = mapped_column(sa.JSON, nullable=True)
    created_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    updated_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )

    assets: Mapped[list["StrategyAsset"]] = relationship(
        "StrategyAsset", back_populates="strategy", cascade="all, delete-orphan",
        order_by="StrategyAsset.leg_num",
    )
    exchange_refs: Mapped[list["StrategyExchangeRef"]] = relationship(
        "StrategyExchangeRef", back_populates="strategy", cascade="all, delete-orphan",
        order_by="StrategyExchangeRef.exchange_num",
    )

    def __repr__(self) -> str:
        return f"<StrategyConfig(id={self.id}, name={self.name}, class={self.strategy_class})>"
