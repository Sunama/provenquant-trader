import sqlalchemy as sa
from app.db.base_class import Base
from sqlalchemy.orm import Mapped, mapped_column


class AppSetting(Base):
    """Key-value store for runtime-configurable settings (e.g. ProvenQuant API key)."""
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(sa.String(100), primary_key=True)
    value: Mapped[str] = mapped_column(sa.Text, nullable=False)
