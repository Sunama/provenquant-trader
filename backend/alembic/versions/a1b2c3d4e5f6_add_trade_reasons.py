"""add trade open/close reasons

Revision ID: a1b2c3d4e5f6
Revises: 249b525d118d
Create Date: 2026-05-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '249b525d118d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('positions', sa.Column('entry_reason', sa.String(), nullable=True))
    op.add_column('trade_history', sa.Column('reason', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('trade_history', 'reason')
    op.drop_column('positions', 'entry_reason')
