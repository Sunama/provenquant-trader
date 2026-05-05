from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.db.session import SessionLocal
from app.db.models.position import Position
from app.services.strategy_executer import TradeSignal, SignalSide
from app.services.trade_adapter import TradeAdapter

logger = logging.getLogger(__name__)


class TradeExecuter:
    """
    Translates a TradeSignal into actual (paper) orders via TradeAdapter
    and persists the resulting Position to Postgres.

    One instance per Celery task — stateless; all state lives in DB / Redis.
    """

    def __init__(self, adapter: TradeAdapter, strategy_id: str) -> None:
        self._adapter = adapter
        self._strategy_id = strategy_id

    async def execute(self, signal: TradeSignal) -> None:
        current_position = await self._adapter.get_open_position(signal.asset_slug)

        # Close opposite position first
        if current_position and current_position.side != signal.side.value:
            await self._close(current_position.asset_slug, current_position.side, signal.price, "signal")

        # Don't re-enter if already on same side
        if current_position and current_position.side == signal.side.value:
            logger.debug(f"Already {signal.side.value} on {signal.asset_slug}, skipping entry")
            return

        await self._open(signal)

    async def _open(self, signal: TradeSignal) -> None:
        balance = await self._adapter.get_balance()
        cost = balance * signal.size_pct
        size = cost / signal.price

        tp_price = signal.price * (1 + signal.tp_pct) if signal.side == SignalSide.LONG else signal.price * (1 - signal.tp_pct)
        sl_price = signal.price * (1 - signal.sl_pct) if signal.side == SignalSide.LONG else signal.price * (1 + signal.sl_pct)

        result = await self._adapter.open_position(
            asset_slug=signal.asset_slug,
            side=signal.side.value,
            size=size,
            price=signal.price,
            tp_price=tp_price,
            sl_price=sl_price,
        )

        async with SessionLocal() as db:
            pos = Position(
                strategy_id=self._strategy_id,
                asset_slug=signal.asset_slug,
                side=signal.side.value,
                entry_price=result.price,
                entry_time=datetime.now(timezone.utc),
                size=result.size,
                is_open=True,
            )
            db.add(pos)
            await db.commit()

    async def _close(self, asset_slug: str, side: str, price: float, reason: str) -> None:
        result = await self._adapter.close_position(asset_slug, side, price, reason)

        async with SessionLocal() as db:
            from sqlalchemy.future import select
            stmt = (
                select(Position)
                .where(
                    Position.strategy_id == self._strategy_id,
                    Position.asset_slug == asset_slug,
                    Position.is_open == True,
                )
                .order_by(Position.created_at.desc())
                .limit(1)
            )
            row = (await db.execute(stmt)).scalar_one_or_none()
            if row:
                row.exit_price = result.price
                row.exit_time = datetime.now(timezone.utc)
                row.exit_reason = reason
                row.is_open = False

                if row.side == "long":
                    row.pnl = (result.price - row.entry_price) * row.size
                else:
                    row.pnl = (row.entry_price - result.price) * row.size
                row.pnl_pct = row.pnl / (row.entry_price * row.size)

                await db.commit()

    async def check_tp_sl(self, asset_slug: str, current_price: float) -> None:
        """Called by DataCollector or a monitoring task to honour TP/SL levels."""
        import json
        import redis.asyncio as aioredis
        from app.core.settings import settings

        r = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        key = f"paper:position:{asset_slug}"
        raw = await r.get(key)
        if not raw:
            return

        pos = json.loads(raw)
        tp: float | None = pos.get("tp_price")
        sl: float | None = pos.get("sl_price")
        side: str = pos["side"]

        hit_tp = tp and ((side == "long" and current_price >= tp) or (side == "short" and current_price <= tp))
        hit_sl = sl and ((side == "long" and current_price <= sl) or (side == "short" and current_price >= sl))

        if hit_tp:
            await self._close(asset_slug, side, current_price, "tp")
        elif hit_sl:
            await self._close(asset_slug, side, current_price, "sl")
