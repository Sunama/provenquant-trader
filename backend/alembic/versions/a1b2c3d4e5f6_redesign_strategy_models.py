"""redesign strategy models

Revision ID: a1b2c3d4e5f6
Revises: b373ab63da2a
Create Date: 2026-05-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'b373ab63da2a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # Modify strategy_configs: remove asset_slug/timeframe, add new columns
    op.drop_column('strategy_configs', 'asset_slug')
    op.drop_column('strategy_configs', 'timeframe')
    op.add_column('strategy_configs', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('strategy_configs', sa.Column('parameters_schema', sa.JSON(), nullable=True))
    op.add_column('strategy_configs', sa.Column('signal_definitions', sa.JSON(), nullable=True))

    # exchange_accounts
    op.create_table(
        'exchange_accounts',
        sa.Column('id', sa.String(), nullable=False, server_default=sa.text("gen_random_uuid()::text")),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('exchange', sa.String(50), nullable=False),
        sa.Column('api_key', sa.Text(), nullable=False),
        sa.Column('api_secret', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    # strategy_assets
    op.create_table(
        'strategy_assets',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('strategy_id', sa.String(), nullable=False),
        sa.Column('asset_num', sa.Integer(), nullable=False),
        sa.Column('asset_slug', sa.String(50), nullable=False),
        sa.Column('exchange', sa.String(50), nullable=False),
        sa.Column('timeframe', sa.String(10), nullable=False),
        sa.Column('market_type', sa.String(20), nullable=False),
        sa.Column('tick_process', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('description', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['strategy_id'], ['strategy_configs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_strategy_assets_strategy_id'), 'strategy_assets', ['strategy_id'], unique=False)

    # strategy_exchange_refs
    op.create_table(
        'strategy_exchange_refs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('strategy_id', sa.String(), nullable=False),
        sa.Column('exchange_account_id', sa.String(), nullable=False),
        sa.Column('exchange_num', sa.Integer(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['strategy_id'], ['strategy_configs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['exchange_account_id'], ['exchange_accounts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('strategy_id', 'exchange_num', name='uq_strategy_exchange_num'),
    )
    op.create_index(op.f('ix_strategy_exchange_refs_strategy_id'), 'strategy_exchange_refs', ['strategy_id'], unique=False)

    # watched_assets
    op.create_table(
        'watched_assets',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('asset_slug', sa.String(50), nullable=False),
        sa.Column('exchange', sa.String(50), nullable=False),
        sa.Column('market_type', sa.String(20), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('timeframes', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('asset_slug', 'exchange', 'market_type', name='uq_watched_asset'),
    )
    op.create_index(op.f('ix_watched_assets_asset_slug'), 'watched_assets', ['asset_slug'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_watched_assets_asset_slug'), table_name='watched_assets')
    op.drop_table('watched_assets')
    op.drop_index(op.f('ix_strategy_exchange_refs_strategy_id'), table_name='strategy_exchange_refs')
    op.drop_table('strategy_exchange_refs')
    op.drop_index(op.f('ix_strategy_assets_strategy_id'), table_name='strategy_assets')
    op.drop_table('strategy_assets')
    op.drop_table('exchange_accounts')

    op.drop_column('strategy_configs', 'signal_definitions')
    op.drop_column('strategy_configs', 'parameters_schema')
    op.drop_column('strategy_configs', 'description')
    op.add_column('strategy_configs', sa.Column('timeframe', sa.String(), nullable=False, server_default=''))
    op.add_column('strategy_configs', sa.Column('asset_slug', sa.String(), nullable=False, server_default=''))
