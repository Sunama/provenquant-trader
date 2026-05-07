from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone

import redis.asyncio as aioredis
from sqlalchemy import select

from app.core.settings import settings
import app.db.base  # noqa: F401 — registers all ORM models so relationships resolve
from app.db.models.position import Position
from app.db.models.strategy_asset import StrategyAsset
from app.db.session import SessionLocal
from app.services.strategy_executer import SignalSide, TradeSignal
from app.services.trade_adapter.paper import PaperTradeAdapter
from app.services.trade_adapter import TradeAdapter

logger = logging.getLogger(__name__)

_STREAM_KEY = "signals:trade"
_EXEC_STREAM = "executions:broadcast"
_GROUP_NAME = "trade-executer"
_CONSUMER_NAME = f"worker-{os.getpid()}"
_MAX_SIGNAL_AGE_SECONDS = 30  # discard stale signals older than this
_STREAM_MAXLEN = 10000


class TradeExecuterProcess:
    """
    Long-running process that consumes trade signals from Redis Stream "signals:trade"
    via consumer group semantics (at-least-once delivery) and executes them via
    the configured TradeAdapter.

    Signal routing:
      - asset_num → resolved to actual asset_slug via DB (strategy_assets table)
      - exchange_num → resolved to ExchangeAccount, which determines the adapter
      - For paper trading: PaperTradeAdapter (Redis-backed) is used for all exchanges
    """

    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None
        self._running = False

    async def start(self) -> None:
        self._redis = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        await self._ensure_consumer_group()
        self._running = True
        logger.info(f"TradeExecuterProcess started (consumer: {_CONSUMER_NAME})")
        await self._run_loop()

    async def stop(self) -> None:
        self._running = False
        if self._redis:
            await self._redis.aclose()
        logger.info("TradeExecuterProcess stopped")

    async def _ensure_consumer_group(self) -> None:
        try:
            await self._redis.xgroup_create(_STREAM_KEY, _GROUP_NAME, id="$", mkstream=True)
            logger.info(f"Consumer group '{_GROUP_NAME}' created on stream '{_STREAM_KEY}'")
        except Exception as e:
            if "BUSYGROUP" in str(e):
                logger.debug(f"Consumer group '{_GROUP_NAME}' already exists")
            else:
                raise

    async def _run_loop(self) -> None:
        while self._running:
            try:
                entries = await self._redis.xreadgroup(
                    groupname=_GROUP_NAME,
                    consumername=_CONSUMER_NAME,
                    streams={_STREAM_KEY: ">"},
                    count=10,
                    block=1000,
                )
                if not entries:
                    continue
                for _stream, messages in entries:
                    for msg_id, fields in messages:
                        await self._handle_signal(msg_id, fields)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in TradeExecuterProcess run loop")
                await asyncio.sleep(1)

    async def _handle_signal(self, msg_id: str, fields: dict) -> None:
        try:
            ts = float(fields.get("ts", 0))
            if time.time() - ts > _MAX_SIGNAL_AGE_SECONDS:
                logger.warning(f"Discarding stale signal {msg_id} (age={(time.time()-ts):.1f}s)")
                await self._redis.xack(_STREAM_KEY, _GROUP_NAME, msg_id)
                return

            config_id = fields.get("config_id", "")
            strategy_id = fields.get("strategy_id", "")
            asset_num = int(fields.get("asset_num", 0))
            exchange_num = int(fields.get("exchange_num", 0))
            execute = fields.get("execute", "long")
            market_type = fields.get("market_type", "futures")
            amount = float(fields.get("amount", 1.0))
            tp_pct = float(fields["tp_pct"]) if fields.get("tp_pct") else None
            sl_pct = float(fields["sl_pct"]) if fields.get("sl_pct") else None
            price = float(fields["price"]) if fields.get("price") else None

            asset_slug, timeframe = await self._resolve_asset(config_id, asset_num)
            if not asset_slug:
                logger.warning(f"Could not resolve asset_num={asset_num} for config={config_id}")
                await self._redis.xack(_STREAM_KEY, _GROUP_NAME, msg_id)
                return

            signal = TradeSignal(
                execute=SignalSide(execute),
                asset_num=asset_num,
                exchange_num=exchange_num,
                market_type=market_type,
                amount=amount,
                tp_pct=tp_pct,
                sl_pct=sl_pct,
                price=price,
                metadata={"asset_slug": asset_slug, "timeframe": timeframe},
            )

            adapter = await self._resolve_adapter(config_id, exchange_num)
            await self._execute_signal(signal, adapter, strategy_id, asset_slug, price)

            await self._redis.xack(_STREAM_KEY, _GROUP_NAME, msg_id)

        except Exception:
            logger.exception(f"Error handling signal {msg_id}")
            # Do not ack — will be re-delivered (at-least-once)

    async def _resolve_asset(self, config_id: str, asset_num: int) -> tuple[str, str]:
        async with SessionLocal() as session:
            result = await session.execute(
                select(StrategyAsset).where(
                    StrategyAsset.strategy_id == config_id,
                    StrategyAsset.asset_num == asset_num,
                )
            )
            asset = result.scalar_one_or_none()
        if asset:
            return asset.asset_slug, asset.timeframe
        return "", ""

    async def _resolve_adapter(self, config_id: str, exchange_num: int) -> TradeAdapter:
        # Currently always returns PaperTradeAdapter.
        # Future: resolve ExchangeAccount by config_id + exchange_num,
        # decrypt credentials, return real exchange adapter.
        return PaperTradeAdapter()

    async def _execute_signal(
        self,
        signal: TradeSignal,
        adapter: TradeAdapter,
        strategy_id: str,
        asset_slug: str,
        signal_price: float | None,
    ) -> None:
        current_position = await adapter.get_open_position(asset_slug)

        if current_position and current_position.side != signal.execute.value:
            await self._close_position(adapter, strategy_id, asset_slug, current_position.side, signal_price, "signal")

        if current_position and current_position.side == signal.execute.value:
            logger.debug(f"Already {signal.execute.value} on {asset_slug}, skipping entry")
            return

        await self._open_position(adapter, strategy_id, asset_slug, signal, signal_price)

    async def _open_position(
        self,
        adapter: TradeAdapter,
        strategy_id: str,
        asset_slug: str,
        signal: TradeSignal,
        price: float | None,
    ) -> None:
        balance = await adapter.get_balance()
        entry_price = price or balance  # fallback, should always have price
        cost = balance * signal.amount
        size = cost / entry_price if entry_price else 0

        is_long = signal.execute in (SignalSide.LONG, SignalSide.BUY, SignalSide.CALL)
        tp_price = None
        sl_price = None
        if signal.tp_pct:
            tp_price = entry_price * (1 + signal.tp_pct) if is_long else entry_price * (1 - signal.tp_pct)
        if signal.sl_pct:
            sl_price = entry_price * (1 - signal.sl_pct) if is_long else entry_price * (1 + signal.sl_pct)

        result = await adapter.open_position(
            asset_slug=asset_slug,
            side=signal.execute.value,
            size=size,
            price=entry_price,
            tp_price=tp_price,
            sl_price=sl_price,
        )

        async with SessionLocal() as db:
            pos = Position(
                strategy_id=strategy_id,
                asset_slug=asset_slug,
                side=signal.execute.value,
                entry_price=result.price,
                entry_time=datetime.now(timezone.utc),
                size=result.size,
                is_open=True,
            )
            db.add(pos)
            await db.commit()
            await db.refresh(pos)

        await self._broadcast_execution(
            action="open",
            strategy_id=strategy_id,
            asset_slug=asset_slug,
            side=signal.execute.value,
            price=result.price,
            size=result.size,
            position_id=pos.id,
        )
        logger.info(f"Opened {signal.execute.value} position on {asset_slug} @ {result.price}")

    async def _close_position(
        self,
        adapter: TradeAdapter,
        strategy_id: str,
        asset_slug: str,
        side: str,
        price: float | None,
        reason: str,
    ) -> None:
        result = await adapter.close_position(asset_slug, side, price or 0, reason)

        async with SessionLocal() as db:
            from sqlalchemy.future import select as fselect
            stmt = (
                fselect(Position)
                .where(
                    Position.strategy_id == strategy_id,
                    Position.asset_slug == asset_slug,
                    Position.is_open == True,  # noqa: E712
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

                if row.side in ("long", "buy", "call"):
                    row.pnl = (result.price - row.entry_price) * row.size
                else:
                    row.pnl = (row.entry_price - result.price) * row.size
                row.pnl_pct = row.pnl / (row.entry_price * row.size) if row.entry_price and row.size else 0
                await db.commit()

                await self._broadcast_execution(
                    action="close",
                    strategy_id=strategy_id,
                    asset_slug=asset_slug,
                    side=side,
                    price=result.price,
                    size=row.size,
                    position_id=row.id,
                    reason=reason,
                    pnl=row.pnl,
                    pnl_pct=row.pnl_pct,
                )

    async def _broadcast_execution(self, action: str, **kwargs) -> None:
        payload = {"action": action, "ts": str(time.time()), **{k: str(v) for k, v in kwargs.items()}}
        await self._redis.xadd(_EXEC_STREAM, payload, maxlen=_STREAM_MAXLEN)
