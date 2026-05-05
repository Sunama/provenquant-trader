from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis

from app.core.settings import settings
from app.services.trade_adapter import TradeAdapter, OrderResult, PositionInfo

logger = logging.getLogger(__name__)

_BALANCE_KEY = "paper:balance"
_POSITION_KEY = "paper:position:{asset_slug}"


class PaperTradeAdapter(TradeAdapter):
    """
    Simulates trade execution in Redis without touching a real exchange.

    Balance and open positions are stored as Redis keys so they survive
    across Celery task invocations.  DataCollector periodically persists
    closed positions to Postgres.

    Default starting balance: 10,000 USDT.
    """

    DEFAULT_BALANCE = 10_000.0

    def __init__(self, initial_balance: float = DEFAULT_BALANCE) -> None:
        self._initial_balance = initial_balance
        self._redis: aioredis.Redis | None = None

    async def _get_redis(self) -> aioredis.Redis:
        if not self._redis:
            self._redis = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._redis

    # ── TradeAdapter interface ─────────────────────────────────────

    async def get_balance(self) -> float:
        r = await self._get_redis()
        val = await r.get(_BALANCE_KEY)
        if val is None:
            await r.set(_BALANCE_KEY, self._initial_balance)
            return self._initial_balance
        return float(val)

    async def open_position(
        self,
        asset_slug: str,
        side: str,
        size: float,
        price: float,
        tp_price: Optional[float] = None,
        sl_price: Optional[float] = None,
    ) -> OrderResult:
        r = await self._get_redis()

        # Deduct cost from balance
        cost = size * price
        balance = await self.get_balance()
        if cost > balance:
            raise ValueError(f"Insufficient paper balance: need {cost:.2f}, have {balance:.2f}")

        await r.incrbyfloat(_BALANCE_KEY, -cost)

        position = {
            "asset_slug": asset_slug,
            "side": side,
            "size": size,
            "entry_price": price,
            "entry_time": datetime.now(timezone.utc).isoformat(),
            "tp_price": tp_price,
            "sl_price": sl_price,
        }
        key = _POSITION_KEY.format(asset_slug=asset_slug)
        await r.set(key, json.dumps(position))

        order_id = str(uuid.uuid4())
        logger.info(f"[PAPER] Opened {side} {asset_slug} size={size} @ {price}")
        return OrderResult(
            order_id=order_id,
            asset_slug=asset_slug,
            side=side,
            price=price,
            size=size,
            status="filled",
        )

    async def close_position(
        self,
        asset_slug: str,
        side: str,
        price: float,
        reason: str = "signal",
    ) -> OrderResult:
        r = await self._get_redis()
        key = _POSITION_KEY.format(asset_slug=asset_slug)
        raw = await r.get(key)
        if not raw:
            raise ValueError(f"No open position for {asset_slug}")

        pos = json.loads(raw)
        entry_price: float = pos["entry_price"]
        size: float = pos["size"]

        if pos["side"] == "long":
            pnl = (price - entry_price) * size
        else:
            pnl = (entry_price - price) * size

        # Return proceeds to balance
        proceeds = size * price + pnl
        await r.incrbyfloat(_BALANCE_KEY, proceeds)
        await r.delete(key)

        logger.info(f"[PAPER] Closed {side} {asset_slug} size={size} @ {price} PnL={pnl:+.2f} reason={reason}")
        return OrderResult(
            order_id=str(uuid.uuid4()),
            asset_slug=asset_slug,
            side=side,
            price=price,
            size=size,
            status="filled",
        )

    async def get_open_position(self, asset_slug: str) -> Optional[PositionInfo]:
        r = await self._get_redis()
        key = _POSITION_KEY.format(asset_slug=asset_slug)
        raw = await r.get(key)
        if not raw:
            return None

        pos = json.loads(raw)
        entry_price: float = pos["entry_price"]
        size: float = pos["size"]
        # We don't have a live price here; caller supplies current price via close_position
        return PositionInfo(
            asset_slug=pos["asset_slug"],
            side=pos["side"],
            size=size,
            entry_price=entry_price,
            unrealised_pnl=0.0,
            unrealised_pnl_pct=0.0,
        )
