"""paper trade exchange account

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-07

"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'exchange_accounts',
        sa.Column('is_paper', sa.Boolean(), nullable=False, server_default='false'),
    )
    op.alter_column('exchange_accounts', 'api_key', nullable=True)
    op.alter_column('exchange_accounts', 'api_secret', nullable=True)


def downgrade():
    op.execute("UPDATE exchange_accounts SET api_key = '' WHERE api_key IS NULL")
    op.execute("UPDATE exchange_accounts SET api_secret = '' WHERE api_secret IS NULL")
    op.alter_column('exchange_accounts', 'api_key', nullable=False)
    op.alter_column('exchange_accounts', 'api_secret', nullable=False)
    op.drop_column('exchange_accounts', 'is_paper')
