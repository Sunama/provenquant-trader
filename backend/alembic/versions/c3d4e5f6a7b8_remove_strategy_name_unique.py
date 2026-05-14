"""remove unique constraint on strategy_configs.name

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-14 00:02:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('strategy_configs_name_key', 'strategy_configs', type_='unique')


def downgrade() -> None:
    op.create_unique_constraint('strategy_configs_name_key', 'strategy_configs', ['name'])
