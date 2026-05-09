from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis

from app.core.settings import settings
from app.services.strategy_executer import PriceMethod
from app.services.trade_adapter import OrderRecord, OrderResult, PositionInfo, TradeAdapter

logger = logging.getLogger(__name__)

# Redis key templates (all scoped by config_id to isolate parallel paper strategies)
_ASSET_KEY    = "paper:{config_id}:asset:{asset}"
_POSITION_KEY = "paper:{config_id}:position:{symbol}"
_PENDING_KEY  = "paper:{config_id}:pending:{order_id}"
_PENDING_SET  = "paper:{config_id}:pending_orders"


class PaperTradeAdapter(TradeAdapter):
    """
    Simulates trade execution in Redis without touching a real exchange.

    Per-asset balances are stored so the adapter correctly handles both
    spot (BTC ↔ USDT swaps) and futures (USDT margin only).

    For limit orders, the order is stored as pending; the caller is
    responsible for calling check_pending_orders() on each tick to
    simulate fills when the market price crosses the limit.
    """

    DEFAULT_QUOTE = "USDT"
    DEFAULT_BALANCE = 10_000.0

    def __init__(
        self,
        config_id: str = "default",
        initial_assets: dict[str, float] | None = None,
    ) -> None:
        self._config_id = config_id
        self._initial_assets: dict[str, float] = initial_assets or {self.DEFAULT_QUOTE: self.DEFAULT_BALANCE}
        self._redis: aioredis.Redis | None = None

    async def _get_redis(self) -> aioredis.Redis:
        if not self._redis:
            self._redis = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._redis

    def _asset_key(self, asset: str) -> str:
        return _ASSET_KEY.format(config_id=self._config_id, asset=asset.upper())

    def _position_key(self, symbol: str) -> str:
        return _POSITION_KEY.format(config_id=self._config_id, symbol=symbol)

    def _pending_key(self, order_id: str) -> str:
        return _PENDING_KEY.format(config_id=self._config_id, order_id=order_id)

    def _pending_set(self) -> str:
        return _PENDING_SET.format(config_id=self._config_id)

    # ── Balance helpers ───────────────────────────────────────────

    async def _seed_if_empty(self) -> None:
        r = await self._get_redis()
        for asset, qty in self._initial_assets.items():
            key = self._asset_key(asset)
            if not await r.exists(key):
                await r.set(key, qty)

    async def get_balance(self) -> float:
        """Return USDT balance (primary quote asset)."""
        return await self.get_asset_balance(self.DEFAULT_QUOTE)

    async def get_asset_balance(self, asset: str) -> float:
        await self._seed_if_empty()
        r = await self._get_redis()
        val = await r.get(self._asset_key(asset))
        return float(val) if val is not None else 0.0

    async def get_all_balances(self) -> dict[str, float]:
        await self._seed_if_empty()
        r = await self._get_redis()
        result: dict[str, float] = {}
        for asset in self._initial_assets:
            val = await r.get(self._asset_key(asset))
            if val:
                qty = float(val)
                if qty != 0:
                    result[asset] = qty
        return result

    # ── TradeAdapter interface ─────────────────────────────────────

    async def open_position(
        self,
        symbol: str,
        side: str,
        size: float,
        price: float,
        tp_price: Optional[float] = None,
        sl_price: Optional[float] = None,
        price_method: PriceMethod = PriceMethod.MARKET,
    ) -> OrderResult:
        order_id = str(uuid.uuid4())

        if price_method == PriceMethod.LIMIT:
            return await self._place_limit_order(symbol, side, size, price, tp_price, sl_price, order_id)

        return await self._fill_immediately(symbol, side, size, price, tp_price, sl_price, order_id)

    async def _fill_immediately(
        self,
        symbol: str,
        side: str,
        size: float,
        price: float,
        tp_price: Optional[float],
        sl_price: Optional[float],
        order_id: str,
    ) -> OrderResult:
        r = await self._get_redis()
        await self._seed_if_empty()

        cost = size * price
        usdt_bal = await self.get_asset_balance(self.DEFAULT_QUOTE)
        if cost > usdt_bal:
            raise ValueError(f"Insufficient paper balance: need {cost:.2f} USDT, have {usdt_bal:.2f}")

        await r.incrbyfloat(self._asset_key(self.DEFAULT_QUOTE), -cost)

        position = {
            "symbol": symbol,
            "side": side,
            "size": size,
            "entry_price": price,
            "entry_time": datetime.now(timezone.utc).isoformat(),
            "tp_price": tp_price,
            "sl_price": sl_price,
        }
        await r.set(self._position_key(symbol), json.dumps(position))

        logger.info(f"[PAPER] Opened {side} {symbol} size={size} @ {price}")
        return OrderResult(
            order_id=order_id,
            symbol=symbol,
            side=side,
            price=price,
            size=size,
            status="filled",
        )

    async def _place_limit_order(
        self,
        symbol: str,
        side: str,
        size: float,
        limit_price: float,
        tp_price: Optional[float],
        sl_price: Optional[float],
        order_id: str,
    ) -> OrderResult:
        r = await self._get_redis()
        order = {
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "size": size,
            "limit_price": limit_price,
            "tp_price": tp_price,
            "sl_price": sl_price,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await r.set(self._pending_key(order_id), json.dumps(order))
        await r.sadd(self._pending_set(), order_id)
        logger.info(f"[PAPER] Pending limit {side} {symbol} size={size} @ {limit_price}")
        return OrderResult(
            order_id=order_id,
            symbol=symbol,
            side=side,
            price=limit_price,
            size=size,
            status="pending",
        )

    async def close_position(
        self,
        symbol: str,
        side: str,
        price: float,
        reason: str = "signal",
    ) -> OrderResult:
        r = await self._get_redis()
        key = self._position_key(symbol)
        raw = await r.get(key)
        if not raw:
            raise ValueError(f"No open position for {symbol}")

        pos = json.loads(raw)
        entry_price: float = pos["entry_price"]
        size: float = pos["size"]

        is_long = side == "long"
        if is_long:
            pnl = (price - entry_price) * size
        else:
            pnl = (entry_price - price) * size

        proceeds = size * price + pnl
        await r.incrbyfloat(self._asset_key(self.DEFAULT_QUOTE), proceeds)
        await r.delete(key)

        logger.info(f"[PAPER] Closed {side} {symbol} size={size} @ {price} PnL={pnl:+.2f} reason={reason}")
        return OrderResult(
            order_id=str(uuid.uuid4()),
            symbol=symbol,
            side=side,
            price=price,
            size=size,
            status="filled",
        )

    async def get_open_position(self, symbol: str) -> Optional[PositionInfo]:
        r = await self._get_redis()
        key = self._position_key(symbol)
        raw = await r.get(key)
        if not raw:
            return None

        pos = json.loads(raw)
        return PositionInfo(
            symbol=pos["symbol"],
            side=pos["side"],
            size=pos["size"],
            entry_price=pos["entry_price"],
            unrealised_pnl=0.0,
            unrealised_pnl_pct=0.0,
        )

    async def get_order_history(self, symbol: str, limit: int = 50) -> list[OrderRecord]:
        """Paper trade has no persistent order history — returns empty list."""
        return []

    # ── Limit order simulation ────────────────────────────────────

    async def check_pending_orders(self, symbol: str, current_price: float) -> list[OrderResult]:
        """
        Check pending limit orders for symbol and fill any whose price is met.
        Call this on each tick for the symbol.

        For long limit orders: fills when current_price <= limit_price
        For short limit orders: fills when current_price >= limit_price
        """
        r = await self._get_redis()
        order_ids = await r.smembers(self._pending_set())
        filled: list[OrderResult] = []

        for oid in order_ids:
            raw = await r.get(self._pending_key(oid))
            if not raw:
                await r.srem(self._pending_set(), oid)
                continue
            order = json.loads(raw)
            if order["symbol"] != symbol:
                continue

            side = order["side"]
            limit_price = float(order["limit_price"])
            should_fill = (
                (side == "long" and current_price <= limit_price) or
                (side == "short" and current_price >= limit_price)
            )
            if should_fill:
                result = await self._fill_immediately(
                    symbol=symbol,
                    side=side,
                    size=float(order["size"]),
                    price=limit_price,
                    tp_price=order.get("tp_price"),
                    sl_price=order.get("sl_price"),
                    order_id=oid,
                )
                await r.delete(self._pending_key(oid))
                await r.srem(self._pending_set(), oid)
                filled.append(result)
                logger.info(f"[PAPER] Limit order filled: {oid} {side} {symbol} @ {limit_price}")

        return filled
