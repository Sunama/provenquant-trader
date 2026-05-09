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
from app.db.models.strategy_config import StrategyConfig
from app.db.models.trade_history import TradeHistory
from app.db.session import SessionLocal
from app.services.strategy_executer import PriceMethod, SignalAction, TradeSignal
from app.services.trade_adapter.paper import PaperTradeAdapter
from app.services.trade_adapter import TradeAdapter

logger = logging.getLogger(__name__)

_STREAM_KEY = "signals:trade"
_EXEC_STREAM = "executions:broadcast"
_GROUP_NAME = "trade-executer"
_CONSUMER_NAME = f"worker-{os.getpid()}"
_MAX_SIGNAL_AGE_SECONDS = 30  # discard stale signals older than this
_STREAM_MAXLEN = 10000

# Actions that open a new position
_OPENING_ACTIONS = {SignalAction.OPEN_LONG, SignalAction.OPEN_SHORT, SignalAction.BUY}
# Actions that close an existing position
_CLOSING_ACTIONS = {SignalAction.CLOSE_LONG, SignalAction.CLOSE_SHORT, SignalAction.SELL}
# Mapping from open action to its corresponding side string (for Position.side)
_ACTION_TO_SIDE = {
    SignalAction.OPEN_LONG: "long",
    SignalAction.OPEN_SHORT: "short",
    SignalAction.BUY: "long",
    SignalAction.SELL: "short",
    SignalAction.CLOSE_LONG: "long",
    SignalAction.CLOSE_SHORT: "short",
}


class TradeExecuterProcess:
    """
    Long-running process that consumes trade signals from Redis Stream "signals:trade"
    via consumer group semantics (at-least-once delivery) and executes them via
    the configured TradeAdapter.

    Signal routing:
      - asset_num → resolved to actual symbol via DB (strategy_assets table)
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
            execute_str = fields.get("execute", "open_long")
            market_type = fields.get("market_type", "futures")
            amount = float(fields.get("amount", 1.0))
            price_method_str = fields.get("price_method", "market")
            tp_pct = float(fields["tp_pct"]) if fields.get("tp_pct") else None
            sl_pct = float(fields["sl_pct"]) if fields.get("sl_pct") else None
            price = float(fields["price"]) if fields.get("price") else None

            try:
                execute = SignalAction(execute_str)
            except ValueError:
                logger.warning(f"Unknown SignalAction '{execute_str}', skipping")
                await self._redis.xack(_STREAM_KEY, _GROUP_NAME, msg_id)
                return

            try:
                price_method = PriceMethod(price_method_str)
            except ValueError:
                price_method = PriceMethod.MARKET

            asset_symbol, timeframe, base_asset, quote_asset = await self._resolve_asset(config_id, asset_num)
            if not asset_symbol:
                logger.warning(f"Could not resolve asset_num={asset_num} for config={config_id}")
                await self._redis.xack(_STREAM_KEY, _GROUP_NAME, msg_id)
                return

            signal = TradeSignal(
                execute=execute,
                asset_num=asset_num,
                exchange_num=exchange_num,
                market_type=market_type,
                amount=amount,
                price_method=price_method,
                tp_pct=tp_pct,
                sl_pct=sl_pct,
                price=price,
                metadata={"symbol": asset_symbol, "timeframe": timeframe},
            )

            adapter = await self._resolve_adapter(config_id, exchange_num)
            await self._execute_signal(
                signal, adapter, strategy_id, asset_symbol,
                base_asset, quote_asset, price,
            )

            await self._redis.xack(_STREAM_KEY, _GROUP_NAME, msg_id)

        except Exception:
            logger.exception(f"Error handling signal {msg_id}")
            # Do not ack — will be re-delivered (at-least-once)

    async def _resolve_asset(self, config_id: str, asset_num: int) -> tuple[str, str, str, str]:
        async with SessionLocal() as session:
            result = await session.execute(
                select(StrategyAsset).where(
                    StrategyAsset.strategy_id == config_id,
                    StrategyAsset.asset_num == asset_num,
                )
            )
            asset = result.scalar_one_or_none()
        if asset:
            return asset.symbol, asset.timeframe, asset.base_asset or "", asset.quote_asset or ""
        return "", "", "", ""

    async def _resolve_adapter(self, config_id: str, exchange_num: int) -> TradeAdapter:
        async with SessionLocal() as session:
            config = await session.get(StrategyConfig, config_id)
        if not config or config.is_paper:
            initial_assets = {}
            if config and config.params:
                initial_assets = config.params.get("initial_assets", {})
            return PaperTradeAdapter(config_id=config_id, initial_assets=initial_assets)
        # TODO: resolve ExchangeAccount by config_id + exchange_num,
        # decrypt credentials, and return BinanceLiveAdapter.
        logger.warning(f"Live adapter not implemented for config={config_id}, falling back to paper")
        return PaperTradeAdapter(config_id=config_id)

    async def _execute_signal(
        self,
        signal: TradeSignal,
        adapter: TradeAdapter,
        strategy_id: str,
        symbol: str,
        base_asset: str,
        quote_asset: str,
        signal_price: float | None,
    ) -> None:
        execute = signal.execute

        if execute in _CLOSING_ACTIONS:
            # Pure close signal
            side = _ACTION_TO_SIDE[execute]
            current = await adapter.get_open_position(symbol)
            if current:
                await self._close_position(
                    adapter, strategy_id, symbol, side, signal_price, "signal",
                    base_asset, quote_asset,
                )
            else:
                logger.debug(f"CLOSE signal for {symbol} but no open position — ignoring")
            return

        # Opening signal — close opposite side first if needed
        new_side = _ACTION_TO_SIDE[execute]
        current = await adapter.get_open_position(symbol)
        if current and current.side != new_side:
            await self._close_position(
                adapter, strategy_id, symbol, current.side, signal_price, "signal",
                base_asset, quote_asset,
            )
        elif current and current.side == new_side:
            logger.debug(f"Already {new_side} on {symbol}, skipping entry")
            return

        await self._open_position(
            adapter, strategy_id, symbol, signal, signal_price, base_asset, quote_asset,
        )

    async def _open_position(
        self,
        adapter: TradeAdapter,
        strategy_id: str,
        symbol: str,
        signal: TradeSignal,
        price: float | None,
        base_asset: str,
        quote_asset: str,
    ) -> None:
        balance = await adapter.get_balance()
        entry_price = price or balance
        cost = balance * signal.amount
        size = cost / entry_price if entry_price else 0

        side = _ACTION_TO_SIDE[signal.execute]
        is_long = side == "long"
        tp_price = None
        sl_price = None
        if signal.tp_pct:
            tp_price = entry_price * (1 + signal.tp_pct) if is_long else entry_price * (1 - signal.tp_pct)
        if signal.sl_pct:
            sl_price = entry_price * (1 - signal.sl_pct) if is_long else entry_price * (1 + signal.sl_pct)

        result = await adapter.open_position(
            symbol=symbol,
            side=side,
            size=size,
            price=entry_price,
            tp_price=tp_price,
            sl_price=sl_price,
            price_method=signal.price_method,
        )

        async with SessionLocal() as db:
            pos = Position(
                strategy_id=strategy_id,
                symbol=symbol,
                side=side,
                entry_price=result.price,
                entry_time=datetime.now(timezone.utc),
                size=result.size,
                is_open=True,
            )
            db.add(pos)

            th = TradeHistory(
                strategy_id=strategy_id,
                occurred_at=datetime.now(timezone.utc),
                trade_type=signal.execute.value,
                symbol=symbol,
                base_asset=base_asset,
                quote_asset=quote_asset,
                bought_asset=base_asset if is_long else quote_asset,
                sold_asset=quote_asset if is_long else base_asset,
                bought_qty=result.size if is_long else cost,
                sold_qty=cost if is_long else result.size,
                exchange_rate=result.price,
                fee=0.0,
                fee_asset=quote_asset,
                exchange="binance",
                market_type=signal.market_type,
            )
            db.add(th)

            await db.commit()
            await db.refresh(pos)

        await self._broadcast_execution(
            action="open",
            strategy_id=strategy_id,
            symbol=symbol,
            side=side,
            price=result.price,
            size=result.size,
            position_id=pos.id,
        )
        logger.info(f"Opened {side} position on {symbol} @ {result.price}")

    async def _close_position(
        self,
        adapter: TradeAdapter,
        strategy_id: str,
        symbol: str,
        side: str,
        price: float | None,
        reason: str,
        base_asset: str,
        quote_asset: str,
    ) -> None:
        result = await adapter.close_position(symbol, side, price or 0, reason)

        async with SessionLocal() as db:
            from sqlalchemy.future import select as fselect
            stmt = (
                fselect(Position)
                .where(
                    Position.strategy_id == strategy_id,
                    Position.symbol == symbol,
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

                is_long = side == "long"
                if is_long:
                    row.pnl = (result.price - row.entry_price) * row.size
                else:
                    row.pnl = (row.entry_price - result.price) * row.size
                row.pnl_pct = row.pnl / (row.entry_price * row.size) if row.entry_price and row.size else 0

                close_action = SignalAction.CLOSE_LONG if is_long else SignalAction.CLOSE_SHORT
                th = TradeHistory(
                    strategy_id=strategy_id,
                    occurred_at=datetime.now(timezone.utc),
                    trade_type=close_action.value,
                    symbol=symbol,
                    base_asset=base_asset,
                    quote_asset=quote_asset,
                    bought_asset=quote_asset if is_long else base_asset,
                    sold_asset=base_asset if is_long else quote_asset,
                    bought_qty=result.size * result.price if is_long else result.size,
                    sold_qty=result.size if is_long else result.size * result.price,
                    exchange_rate=result.price,
                    fee=0.0,
                    fee_asset=quote_asset,
                    exchange="binance",
                    market_type="futures",
                )
                db.add(th)
                await db.commit()

                await self._broadcast_execution(
                    action="close",
                    strategy_id=strategy_id,
                    symbol=symbol,
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
