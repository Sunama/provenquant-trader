"""rename asset_slug to symbol, add trade_history, add base/quote assets

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-09

"""
from alembic import op
import sqlalchemy as sa

revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    # ── ticks ─────────────────────────────────────────────────────
    op.drop_constraint("uq_tick", "ticks", type_="unique")
    op.alter_column("ticks", "asset_slug", new_column_name="symbol")
    op.create_unique_constraint("uq_tick", "ticks", ["symbol", "timeframe", "time"])

    # ── watched_assets ────────────────────────────────────────────
    op.drop_constraint("uq_watched_asset", "watched_assets", type_="unique")
    op.alter_column("watched_assets", "asset_slug", new_column_name="symbol")
    op.add_column("watched_assets", sa.Column("base_asset", sa.String(20), nullable=True))
    op.add_column("watched_assets", sa.Column("quote_asset", sa.String(20), nullable=True))
    op.create_unique_constraint("uq_watched_asset", "watched_assets", ["symbol", "exchange", "market_type"])

    # ── positions ─────────────────────────────────────────────────
    op.alter_column("positions", "asset_slug", new_column_name="symbol")

    # ── strategy_assets ───────────────────────────────────────────
    op.alter_column("strategy_assets", "asset_slug", new_column_name="symbol")
    op.add_column("strategy_assets", sa.Column("base_asset", sa.String(20), nullable=True))
    op.add_column("strategy_assets", sa.Column("quote_asset", sa.String(20), nullable=True))

    # ── market data tables ────────────────────────────────────────
    op.drop_constraint("uq_funding_rate", "funding_rates", type_="unique")
    op.alter_column("funding_rates", "asset_slug", new_column_name="symbol")
    op.create_unique_constraint("uq_funding_rate", "funding_rates", ["symbol", "exchange", "time"])

    op.drop_constraint("uq_mark_price", "mark_prices", type_="unique")
    op.alter_column("mark_prices", "asset_slug", new_column_name="symbol")
    op.create_unique_constraint("uq_mark_price", "mark_prices", ["symbol", "exchange", "market_type", "time"])

    op.drop_constraint("uq_open_interest", "open_interest", type_="unique")
    op.alter_column("open_interest", "asset_slug", new_column_name="symbol")
    op.create_unique_constraint("uq_open_interest", "open_interest", ["symbol", "exchange", "time"])

    op.alter_column("liquidations", "asset_slug", new_column_name="symbol")
    op.alter_column("agg_trades", "asset_slug", new_column_name="symbol")

    # ── trade_history ─────────────────────────────────────────────
    op.create_table(
        "trade_history",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("strategy_id", sa.String(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trade_type", sa.String(30), nullable=False),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("base_asset", sa.String(20), nullable=False),
        sa.Column("quote_asset", sa.String(20), nullable=False),
        sa.Column("bought_asset", sa.String(20), nullable=False),
        sa.Column("sold_asset", sa.String(20), nullable=False),
        sa.Column("bought_qty", sa.Float(), nullable=False),
        sa.Column("sold_qty", sa.Float(), nullable=False),
        sa.Column("exchange_rate", sa.Float(), nullable=False),
        sa.Column("fee", sa.Float(), nullable=False, server_default="0"),
        sa.Column("fee_asset", sa.String(20), nullable=False, server_default=""),
        sa.Column("exchange", sa.String(50), nullable=False),
        sa.Column("market_type", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategy_configs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trade_history_strategy_id", "trade_history", ["strategy_id"])
    op.create_index("ix_trade_history_occurred_at", "trade_history", ["occurred_at"])
    op.create_index("ix_trade_history_symbol", "trade_history", ["symbol"])


def downgrade():
    op.drop_table("trade_history")

    op.alter_column("agg_trades", "symbol", new_column_name="asset_slug")
    op.alter_column("liquidations", "symbol", new_column_name="asset_slug")

    op.drop_constraint("uq_open_interest", "open_interest", type_="unique")
    op.alter_column("open_interest", "symbol", new_column_name="asset_slug")
    op.create_unique_constraint("uq_open_interest", "open_interest", ["asset_slug", "exchange", "time"])

    op.drop_constraint("uq_mark_price", "mark_prices", type_="unique")
    op.alter_column("mark_prices", "symbol", new_column_name="asset_slug")
    op.create_unique_constraint("uq_mark_price", "mark_prices", ["asset_slug", "exchange", "market_type", "time"])

    op.drop_constraint("uq_funding_rate", "funding_rates", type_="unique")
    op.alter_column("funding_rates", "symbol", new_column_name="asset_slug")
    op.create_unique_constraint("uq_funding_rate", "funding_rates", ["asset_slug", "exchange", "time"])

    op.drop_column("strategy_assets", "quote_asset")
    op.drop_column("strategy_assets", "base_asset")
    op.alter_column("strategy_assets", "symbol", new_column_name="asset_slug")

    op.alter_column("positions", "symbol", new_column_name="asset_slug")

    op.drop_constraint("uq_watched_asset", "watched_assets", type_="unique")
    op.drop_column("watched_assets", "quote_asset")
    op.drop_column("watched_assets", "base_asset")
    op.alter_column("watched_assets", "symbol", new_column_name="asset_slug")
    op.create_unique_constraint("uq_watched_asset", "watched_assets", ["asset_slug", "exchange", "market_type"])

    op.drop_constraint("uq_tick", "ticks", type_="unique")
    op.alter_column("ticks", "symbol", new_column_name="asset_slug")
    op.create_unique_constraint("uq_tick", "ticks", ["asset_slug", "timeframe", "time"])
