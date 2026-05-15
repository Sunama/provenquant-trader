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
from app.services.strategy_executer import AmountMode, LegOrder, PriceMethod, SignalAction
from app.services.trade_adapter.paper import PaperTradeAdapter
from app.services.trade_adapter import TradeAdapter

logger = logging.getLogger(__name__)

_STREAM_KEY = "signals:trade"
_EXEC_STREAM = "executions:broadcast"
_CALLBACKS_STREAM = "executions:callbacks"
_GROUP_NAME = "trade-executer"
_CONSUMER_NAME = f"worker-{os.getpid()}"
_MAX_SIGNAL_AGE_SECONDS = 30
_STREAM_MAXLEN = 10000

_OPENING_ACTIONS = {SignalAction.OPEN_LONG, SignalAction.OPEN_SHORT}
_CLOSING_ACTIONS = {SignalAction.CLOSE_LONG, SignalAction.CLOSE_SHORT}
_ACTION_TO_SIDE = {
    SignalAction.OPEN_LONG: "long",
    SignalAction.OPEN_SHORT: "short",
    SignalAction.CLOSE_LONG: "long",
    SignalAction.CLOSE_SHORT: "short",
}


class TradeExecuterProcess:
    """
    Long-running process that consumes ExecutionPlans from Redis Stream "signals:trade"
    via consumer group semantics (at-least-once delivery) and executes them via
    the configured TradeAdapter.

    Each stream message contains a JSON-encoded list of LegOrders. Orders within one
    ExecutionPlan are processed sequentially. If `on_complete` is set on the plan, a
    notification is published to the "executions:callbacks" stream after all orders execute.
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
                        await self._handle_message(msg_id, fields)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in TradeExecuterProcess run loop")
                await asyncio.sleep(1)

    async def _handle_message(self, msg_id: str, fields: dict) -> None:
        try:
            ts = float(fields.get("ts", 0))
            if time.time() - ts > _MAX_SIGNAL_AGE_SECONDS:
                logger.warning(f"Discarding stale signal {msg_id} (age={(time.time()-ts):.1f}s)")
                await self._redis.xack(_STREAM_KEY, _GROUP_NAME, msg_id)
                return

            config_id = fields.get("config_id", "")
            strategy_id = fields.get("strategy_id", config_id)
            on_complete = fields.get("on_complete") or None
            tick_close = float(fields.get("tick_close", 0))
            tick_market_type = fields.get("tick_market_type", "futures")

            raw_orders = fields.get("orders", "[]")
            try:
                orders_data: list[dict] = json.loads(raw_orders)
            except json.JSONDecodeError:
                logger.warning(f"Invalid orders JSON in message {msg_id}")
                await self._redis.xack(_STREAM_KEY, _GROUP_NAME, msg_id)
                return

            orders = [LegOrder.from_dict(o) for o in orders_data]
            if not orders:
                await self._redis.xack(_STREAM_KEY, _GROUP_NAME, msg_id)
                return

            adapter, account_base = await self._resolve_adapter(config_id)
            executed_count = 0

            for order in orders:
                leg_meta = await self._resolve_leg(config_id, order.leg_num)
                if not leg_meta:
                    logger.warning(f"Could not resolve leg_num={order.leg_num} for config={config_id}")
                    continue

                symbol, timeframe, market_type, base_asset, quote_asset, transaction_fee, asset_leverage = leg_meta
                effective_leverage = order.leverage if order.leverage is not None else asset_leverage
                price = order.price if order.price else tick_close

                await self._execute_order(
                    order=order,
                    adapter=adapter,
                    strategy_id=strategy_id,
                    symbol=symbol,
                    market_type=market_type,
                    base_asset=base_asset,
                    quote_asset=quote_asset,
                    signal_price=price,
                    transaction_fee=transaction_fee,
                    account_base=account_base,
                    leverage=effective_leverage,
                )
                executed_count += 1

            if on_complete and executed_count > 0:
                await self._redis.xadd(
                    _CALLBACKS_STREAM,
                    {
                        "config_id": config_id,
                        "strategy_id": strategy_id,
                        "on_complete": on_complete,
                        "executed_orders": str(executed_count),
                        "ts": str(time.time()),
                    },
                    maxlen=_STREAM_MAXLEN,
                )

            await self._redis.xack(_STREAM_KEY, _GROUP_NAME, msg_id)

        except Exception:
            logger.exception(f"Error handling signal {msg_id}")
            # Do not ack — will be re-delivered (at-least-once)

    async def _resolve_leg(self, config_id: str, leg_num: int) -> tuple[str, str, str, str, str, float, float] | None:
        """Returns (symbol, timeframe, market_type, base_asset, quote_asset, transaction_fee, leverage) or None."""
        async with SessionLocal() as session:
            result = await session.execute(
                select(StrategyAsset).where(
                    StrategyAsset.strategy_id == config_id,
                    StrategyAsset.leg_num == leg_num,
                )
            )
            asset = result.scalar_one_or_none()
        if asset:
            return (
                asset.symbol,
                asset.timeframe,
                asset.market_type,
                asset.base_asset or "",
                asset.quote_asset or "",
                asset.transaction_fee,
                asset.leverage,
            )
        return None

    async def _resolve_adapter(self, config_id: str) -> tuple[TradeAdapter, str]:
        async with SessionLocal() as session:
            config = await session.get(StrategyConfig, config_id)
        account_base = (config.base_asset or "USDT") if config else "USDT"
        if not config or config.is_paper:
            initial_assets = config.params.get("initial_assets", {}) if config and config.params else {}
            return PaperTradeAdapter(config_id=config_id, initial_assets=initial_assets), account_base
        logger.warning(f"Live adapter not implemented for config={config_id}, falling back to paper")
        return PaperTradeAdapter(config_id=config_id), account_base

    async def _compute_size(
        self,
        order: LegOrder,
        adapter: TradeAdapter,
        config_id: str,
        symbol: str,
        price: float,
        account_base: str = "USDT",
        leverage: float = 1.0,
    ) -> float:
        """Convert LegOrder.amount + AmountMode into a concrete size (number of units)."""
        if order.amount_mode == AmountMode.UNITS:
            return order.amount

        if order.amount_mode == AmountMode.RATIO_TO_LEG:
            if order.reference_leg is None:
                logger.warning(f"RATIO_TO_LEG without reference_leg for config={config_id}")
                return 0.0
            leg_meta = await self._resolve_leg(config_id, order.reference_leg)
            if not leg_meta:
                return 0.0
            ref_symbol = leg_meta[0]
            ref_pos = await adapter.get_open_position(ref_symbol)
            if not ref_pos:
                return 0.0
            return ref_pos.size * order.amount

        if order.amount_mode == AmountMode.PORTFOLIO_PCT_UNREALIZED:
            # Total portfolio = cash + unrealized value of all open positions
            balance = await adapter.get_asset_balance(account_base)
            # PaperTradeAdapter doesn't expose all open positions; approximate with balance
            # Real implementation would iterate open positions and sum notional value
            portfolio_value = balance  # TODO: add unrealized position values
            cost = portfolio_value * order.amount
            return (cost / price) * leverage if price else 0.0

        # Default: PORTFOLIO_PCT_REALIZED — fraction of account base asset balance
        balance = await adapter.get_asset_balance(account_base)
        cost = balance * order.amount   # margin to use
        return (cost / price) * leverage if price else 0.0

    async def _execute_order(
        self,
        order: LegOrder,
        adapter: TradeAdapter,
        strategy_id: str,
        symbol: str,
        market_type: str,
        base_asset: str,
        quote_asset: str,
        signal_price: float,
        transaction_fee: float = 0.0,
        account_base: str = "USDT",
        leverage: float = 1.0,
    ) -> None:
        execute = order.action

        if execute in _CLOSING_ACTIONS:
            side = _ACTION_TO_SIDE[execute]
            current = await adapter.get_open_position(symbol)
            if current:
                await self._close_position(
                    adapter, strategy_id, symbol, side, signal_price,
                    order.reason or "signal",
                    base_asset, quote_asset, market_type, transaction_fee,
                )
            else:
                logger.debug(f"CLOSE signal for {symbol} but no open position — ignoring")
            return

        new_side = _ACTION_TO_SIDE[execute]
        current = await adapter.get_open_position(symbol)
        if current and current.side != new_side:
            await self._close_position(
                adapter, strategy_id, symbol, current.side, signal_price, "signal",
                base_asset, quote_asset, market_type, transaction_fee,
            )
        elif current and current.side == new_side:
            logger.debug(f"Already {new_side} on {symbol}, skipping entry")
            return

        await self._open_position(
            order=order,
            adapter=adapter,
            strategy_id=strategy_id,
            symbol=symbol,
            market_type=market_type,
            signal_price=signal_price,
            base_asset=base_asset,
            quote_asset=quote_asset,
            transaction_fee=transaction_fee,
            account_base=account_base,
            leverage=leverage,
        )

    async def _open_position(
        self,
        order: LegOrder,
        adapter: TradeAdapter,
        strategy_id: str,
        symbol: str,
        market_type: str,
        signal_price: float,
        base_asset: str,
        quote_asset: str,
        transaction_fee: float = 0.0,
        account_base: str = "USDT",
        leverage: float = 1.0,
    ) -> None:
        entry_price = signal_price or 1.0
        size = await self._compute_size(order, adapter, strategy_id, symbol, entry_price, account_base, leverage)
        if size <= 0:
            logger.warning(f"Computed size=0 for {symbol}, skipping open")
            return

        side = _ACTION_TO_SIDE[order.action]
        is_long = side == "long"
        tp_price = None
        sl_price = None
        if order.tp_pct:
            tp_price = entry_price * (1 + order.tp_pct) if is_long else entry_price * (1 - order.tp_pct)
        if order.sl_pct:
            sl_price = entry_price * (1 - order.sl_pct) if is_long else entry_price * (1 + order.sl_pct)

        result = await adapter.open_position(
            symbol=symbol,
            side=side,
            size=size,
            price=entry_price,
            tp_price=tp_price,
            sl_price=sl_price,
            price_method=order.price_method,
            leverage=leverage,
        )

        notional = result.size * result.price
        margin = notional / leverage
        fee = margin * transaction_fee
        async with SessionLocal() as db:
            pos = Position(
                strategy_id=strategy_id,
                symbol=symbol,
                side=side,
                entry_price=result.price,
                entry_time=datetime.now(timezone.utc),
                size=result.size,
                leverage=leverage,
                is_open=True,
                tp_price=tp_price,
                sl_price=sl_price,
                entry_reason=order.reason,
            )
            db.add(pos)

            th = TradeHistory(
                strategy_id=strategy_id,
                occurred_at=datetime.now(timezone.utc),
                trade_type=order.action.value,
                symbol=symbol,
                base_asset=base_asset,
                quote_asset=quote_asset,
                bought_asset=base_asset if is_long else quote_asset,
                sold_asset=quote_asset if is_long else base_asset,
                bought_qty=result.size if is_long else margin,
                sold_qty=margin if is_long else result.size,
                exchange_rate=result.price,
                fee=fee,
                fee_asset=quote_asset,
                exchange="binance",
                market_type=market_type,
                reason=order.reason,
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
        logger.info(f"Opened {side} position on {symbol} @ {result.price} (size={result.size})")

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
        market_type: str = "futures",
        transaction_fee: float = 0.0,
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
                gross_pnl = (result.price - row.entry_price) * row.size if is_long else (row.entry_price - result.price) * row.size
                close_cost = result.size * result.price
                fee = close_cost * transaction_fee
                row.pnl = gross_pnl - fee
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
                    bought_qty=close_cost if is_long else result.size,
                    sold_qty=result.size if is_long else close_cost,
                    exchange_rate=result.price,
                    fee=fee,
                    fee_asset=quote_asset,
                    exchange="binance",
                    market_type=market_type,
                    reason=reason,
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

