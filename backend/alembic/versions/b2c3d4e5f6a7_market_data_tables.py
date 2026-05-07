"""market data tables

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-07 00:01:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'funding_rates',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('asset_slug', sa.String(50), nullable=False),
        sa.Column('exchange', sa.String(50), nullable=False),
        sa.Column('time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('rate', sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('asset_slug', 'exchange', 'time', name='uq_funding_rate'),
    )
    op.create_index(op.f('ix_funding_rates_asset_slug'), 'funding_rates', ['asset_slug'], unique=False)
    op.create_index(op.f('ix_funding_rates_time'), 'funding_rates', ['time'], unique=False)

    op.create_table(
        'mark_prices',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('asset_slug', sa.String(50), nullable=False),
        sa.Column('exchange', sa.String(50), nullable=False),
        sa.Column('market_type', sa.String(20), nullable=False),
        sa.Column('time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('index_price', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('asset_slug', 'exchange', 'market_type', 'time', name='uq_mark_price'),
    )
    op.create_index(op.f('ix_mark_prices_asset_slug'), 'mark_prices', ['asset_slug'], unique=False)
    op.create_index(op.f('ix_mark_prices_time'), 'mark_prices', ['time'], unique=False)

    op.create_table(
        'open_interest',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('asset_slug', sa.String(50), nullable=False),
        sa.Column('exchange', sa.String(50), nullable=False),
        sa.Column('time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('oi_contracts', sa.Float(), nullable=False),
        sa.Column('oi_value', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('asset_slug', 'exchange', 'time', name='uq_open_interest'),
    )
    op.create_index(op.f('ix_open_interest_asset_slug'), 'open_interest', ['asset_slug'], unique=False)
    op.create_index(op.f('ix_open_interest_time'), 'open_interest', ['time'], unique=False)

    op.create_table(
        'liquidations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('asset_slug', sa.String(50), nullable=False),
        sa.Column('exchange', sa.String(50), nullable=False),
        sa.Column('time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('side', sa.String(20), nullable=False),
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_liquidations_asset_slug'), 'liquidations', ['asset_slug'], unique=False)
    op.create_index(op.f('ix_liquidations_time'), 'liquidations', ['time'], unique=False)

    op.create_table(
        'agg_trades',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('asset_slug', sa.String(50), nullable=False),
        sa.Column('exchange', sa.String(50), nullable=False),
        sa.Column('time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('is_buyer_maker', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_agg_trades_asset_slug'), 'agg_trades', ['asset_slug'], unique=False)
    op.create_index(op.f('ix_agg_trades_time'), 'agg_trades', ['time'], unique=False)

    op.create_table(
        'app_settings',
        sa.Column('key', sa.String(100), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )


def downgrade() -> None:
    op.drop_table('app_settings')
    op.drop_index(op.f('ix_agg_trades_time'), table_name='agg_trades')
    op.drop_index(op.f('ix_agg_trades_asset_slug'), table_name='agg_trades')
    op.drop_table('agg_trades')
    op.drop_index(op.f('ix_liquidations_time'), table_name='liquidations')
    op.drop_index(op.f('ix_liquidations_asset_slug'), table_name='liquidations')
    op.drop_table('liquidations')
    op.drop_index(op.f('ix_open_interest_time'), table_name='open_interest')
    op.drop_index(op.f('ix_open_interest_asset_slug'), table_name='open_interest')
    op.drop_table('open_interest')
    op.drop_index(op.f('ix_mark_prices_time'), table_name='mark_prices')
    op.drop_index(op.f('ix_mark_prices_asset_slug'), table_name='mark_prices')
    op.drop_table('mark_prices')
    op.drop_index(op.f('ix_funding_rates_time'), table_name='funding_rates')
    op.drop_index(op.f('ix_funding_rates_asset_slug'), table_name='funding_rates')
    op.drop_table('funding_rates')
