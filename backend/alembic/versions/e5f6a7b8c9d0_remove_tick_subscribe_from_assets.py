"""remove tick_process and subscribe_depth from strategy_assets

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-15 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("strategy_assets", "tick_process")
    op.drop_column("strategy_assets", "subscribe_depth")


def downgrade() -> None:
    op.add_column(
        "strategy_assets",
        sa.Column("tick_process", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "strategy_assets",
        sa.Column("subscribe_depth", sa.Boolean(), nullable=False, server_default="false"),
    )
