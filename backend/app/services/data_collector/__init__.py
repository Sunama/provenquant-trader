from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone

import redis.asyncio as aioredis
from sqlalchemy.dialects.postgresql import insert

from app.core.settings import settings
from app.db.models.agg_trade import AggTrade
from app.db.models.funding_rate import FundingRate
from app.db.models.liquidation import Liquidation
from app.db.models.mark_price import MarkPrice
from app.db.models.open_interest import OpenInterest
from app.db.models.tick import Tick
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

_STREAM_CONSUMER_GROUP = "data-collector"
_STREAM_CONSUMER_NAME = "collector-1"
_STREAM_BATCH = 500


def _ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


class DataCollector(ABC):
    """
    Base DataCollector — flushed by a Celery beat task every minute.

    Flushes the following Redis buffers → Postgres:
      tick:*:*               → ticks
      funding:*:*            → funding_rates
      mark_price:*:*:*       → mark_prices
      oi:*:*                 → open_interest
      liquidations:buffer    → liquidations  (Redis Stream, XREADGROUP)
      agg_trades:buffer      → agg_trades    (Redis Stream, XREADGROUP)
    """

    async def collect(self) -> int:
        r = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        total = 0
        try:
            async with SessionLocal() as db:
                total += await self._flush_ticks(r, db)
                total += await self._flush_funding_rates(r, db)
                total += await self._flush_mark_prices(r, db)
                total += await self._flush_open_interest(r, db)
                total += await self._flush_stream(r, db, "liquidations:buffer", self._parse_liquidation, Liquidation)
                total += await self._flush_stream(r, db, "agg_trades:buffer", self._parse_agg_trade, AggTrade)
                await db.commit()
        finally:
            await r.aclose()
        return total

    # ── Tick flush ────────────────────────────────────────────────

    async def _flush_ticks(self, r: aioredis.Redis, db) -> int:
        keys = await r.keys("tick:*:*:*")
        rows = []
        for key in keys:
            items = await r.lrange(key, 0, -1)
            await r.delete(key)
            for raw in items:
                try:
                    d = json.loads(raw)
                    rows.append({
                        "symbol": d["symbol"],
                        "timeframe": d["timeframe"],
                        "market_type": d.get("market_type", "futures"),
                        "time": _ms_to_dt(d["time"]),
                        "open": d["open"],
                        "high": d["high"],
                        "low": d["low"],
                        "close": d["close"],
                        "volume": d["volume"],
                    })
                except Exception:
                    logger.exception(f"Failed to parse tick from {key}")
        if rows:
            await db.execute(
                insert(Tick).values(rows).on_conflict_do_nothing(constraint="uq_tick")
            )
        return len(rows)

    # ── Funding rate flush ────────────────────────────────────────

    async def _flush_funding_rates(self, r: aioredis.Redis, db) -> int:
        keys = await r.keys("funding:*:*")
        rows = []
        for key in keys:
            raw = await r.get(key)
            if not raw:
                continue
            try:
                d = json.loads(raw)
                rows.append({
                    "symbol": d["symbol"],
                    "exchange": d["exchange"],
                    "market_type": d.get("market_type", "futures"),
                    "time": _ms_to_dt(d["time"]),
                    "rate": d["rate"],
                })
            except Exception:
                logger.exception(f"Failed to parse funding rate from {key}")
        if rows:
            await db.execute(
                insert(FundingRate).values(rows).on_conflict_do_nothing(constraint="uq_funding_rate")
            )
        return len(rows)

    # ── Mark price flush ──────────────────────────────────────────

    async def _flush_mark_prices(self, r: aioredis.Redis, db) -> int:
        keys = await r.keys("mark_price:*:*:*")
        rows = []
        for key in keys:
            items = await r.lrange(key, 0, -1)
            await r.delete(key)
            for raw in items:
                try:
                    d = json.loads(raw)
                    rows.append({
                        "symbol": d["symbol"],
                        "exchange": d["exchange"],
                        "market_type": d["market_type"],
                        "time": _ms_to_dt(d["time"]),
                        "price": d["price"],
                        "index_price": d.get("index_price"),
                    })
                except Exception:
                    logger.exception(f"Failed to parse mark price from {key}")
        if rows:
            await db.execute(
                insert(MarkPrice).values(rows).on_conflict_do_nothing(constraint="uq_mark_price")
            )
        return len(rows)

    # ── Open interest flush ───────────────────────────────────────

    async def _flush_open_interest(self, r: aioredis.Redis, db) -> int:
        keys = await r.keys("oi:*:*")
        rows = []
        for key in keys:
            items = await r.lrange(key, 0, -1)
            await r.delete(key)
            for raw in items:
                try:
                    d = json.loads(raw)
                    rows.append({
                        "symbol": d["symbol"],
                        "exchange": d["exchange"],
                        "market_type": d.get("market_type", "futures"),
                        "time": _ms_to_dt(d["time"]),
                        "oi_contracts": d["oi_contracts"],
                        "oi_value": d.get("oi_value"),
                    })
                except Exception:
                    logger.exception(f"Failed to parse open interest from {key}")
        if rows:
            await db.execute(
                insert(OpenInterest).values(rows).on_conflict_do_nothing(constraint="uq_open_interest")
            )
        return len(rows)

    # ── Redis Stream flush (liquidations + agg_trades) ────────────

    async def _ensure_consumer_group(self, r: aioredis.Redis, stream: str) -> None:
        try:
            await r.xgroup_create(stream, _STREAM_CONSUMER_GROUP, id="0", mkstream=True)
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                raise

    @staticmethod
    def _parse_liquidation(fields: dict) -> dict:
        return {
            "symbol": fields["symbol"],
            "exchange": fields["exchange"],
            "market_type": fields.get("market_type", "futures"),
            "time": _ms_to_dt(int(fields["time"])),
            "side": fields["side"],
            "price": float(fields["price"]),
            "quantity": float(fields["quantity"]),
        }

    @staticmethod
    def _parse_agg_trade(fields: dict) -> dict:
        return {
            "symbol": fields["symbol"],
            "exchange": fields["exchange"],
            "market_type": fields.get("market_type", "futures"),
            "time": _ms_to_dt(int(fields["time"])),
            "price": float(fields["price"]),
            "quantity": float(fields["quantity"]),
            "is_buyer_maker": fields.get("is_buyer_maker", "False") == "True",
        }

    async def _flush_stream(self, r: aioredis.Redis, db, stream: str, parser, model) -> int:
        await self._ensure_consumer_group(r, stream)
        rows = []
        msg_ids = []

        messages = await r.xreadgroup(
            _STREAM_CONSUMER_GROUP,
            _STREAM_CONSUMER_NAME,
            {stream: ">"},
            count=_STREAM_BATCH,
        )
        if not messages:
            return 0

        for _stream_name, entries in messages:
            for msg_id, fields in entries:
                try:
                    rows.append(parser(fields))
                    msg_ids.append(msg_id)
                except Exception:
                    logger.exception(f"Failed to parse stream message from {stream}")
                    msg_ids.append(msg_id)  # ack bad messages to avoid redelivery loop

        if rows:
            await db.execute(insert(model).values(rows).on_conflict_do_nothing())

        if msg_ids:
            await r.xack(stream, _STREAM_CONSUMER_GROUP, *msg_ids)

        return len(rows)

    @abstractmethod
    async def after_collect(self, tick_count: int) -> None:
        """Hook called after the base collect() — override for custom forwarding."""
        ...


class DefaultDataCollector(DataCollector):
    """Concrete no-op subclass — just flushes Redis → Postgres."""

    async def after_collect(self, tick_count: int) -> None:
        pass
