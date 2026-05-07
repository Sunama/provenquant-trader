import sqlalchemy as sa
from app.db.base_class import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.db.models.strategy_exchange_ref import StrategyExchangeRef


class ExchangeAccount(Base):
    """
    Exchange API credentials.
    For live accounts: api_key/api_secret hold pgp_sym_encrypt ciphertext.
    For paper accounts (is_paper=True): api_key/api_secret are NULL.
    """
    __tablename__ = "exchange_accounts"

    id: Mapped[str] = mapped_column(
        sa.String, primary_key=True, server_default=sa.text("gen_random_uuid()::text")
    )
    name: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    exchange: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    is_paper: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default="false")
    api_key: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    api_secret: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    updated_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )

    strategy_refs: Mapped[list["StrategyExchangeRef"]] = relationship(
        "StrategyExchangeRef", back_populates="exchange_account"
    )

    def __repr__(self) -> str:
        return f"<ExchangeAccount(id={self.id}, name={self.name}, exchange={self.exchange})>"
