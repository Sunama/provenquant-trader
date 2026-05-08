"""strategy_config is_paper

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-08

"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'strategy_configs',
        sa.Column('is_paper', sa.Boolean(), nullable=False, server_default='true'),
    )


def downgrade():
    op.drop_column('strategy_configs', 'is_paper')
