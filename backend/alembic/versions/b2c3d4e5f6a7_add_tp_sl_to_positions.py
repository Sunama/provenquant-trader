"""add tp_price and sl_price to positions

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-14 00:01:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('positions', sa.Column('tp_price', sa.Float(), nullable=True))
    op.add_column('positions', sa.Column('sl_price', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('positions', 'sl_price')
    op.drop_column('positions', 'tp_price')
