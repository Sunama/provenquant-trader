"""add leverage to trade_history and market_type to positions

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('positions', sa.Column('market_type', sa.String(20), nullable=False, server_default='spot'))
    op.add_column('trade_history', sa.Column('leverage', sa.Float(), nullable=False, server_default='1.0'))


def downgrade() -> None:
    op.drop_column('positions', 'market_type')
    op.drop_column('trade_history', 'leverage')
