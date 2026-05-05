from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone

import redis.asyncio as aioredis
from sqlalchemy.dialects.postgresql import insert

from app.core.settings import settings
from app.db.models.tick import Tick
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


class DataCollector(ABC):
    """
    Base DataCollector — flushed by a Celery beat task every minute.

    Default behaviour: drain all tick keys from Redis → upsert to Postgres.
    Override collect() in a subclass to add custom persistence or forwarding.
    """

    async def collect(self) -> int:
        """Returns the number of ticks persisted."""
        r = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        keys = await r.keys("tick:*:*")  # tick:{asset_slug}:{timeframe}

        total = 0
        async with SessionLocal() as db:
            for key in keys:
                items = await r.lrange(key, 0, -1)
                if not items:
                    continue

                rows = []
                for raw in items:
                    try:
                        d = json.loads(raw)
                        rows.append({
                            "asset_slug": d["asset_slug"],
                            "timeframe": d["timeframe"],
                            "time": datetime.fromtimestamp(d["time"] / 1000, tz=timezone.utc),
                            "open": d["open"],
                            "high": d["high"],
                            "low": d["low"],
                            "close": d["close"],
                            "volume": d["volume"],
                        })
                    except Exception:
                        logger.exception(f"Failed to parse tick from key {key}")

                if rows:
                    stmt = (
                        insert(Tick)
                        .values(rows)
                        .on_conflict_do_nothing(
                            constraint="uq_tick"
                        )
                    )
                    await db.execute(stmt)
                    total += len(rows)

            await db.commit()

        await r.aclose()
        return total

    @abstractmethod
    async def after_collect(self, tick_count: int) -> None:
        """Hook called after the base collect() — override for custom forwarding."""
        ...


class DefaultDataCollector(DataCollector):
    """Concrete no-op subclass — just flushes Redis → Postgres."""

    async def after_collect(self, tick_count: int) -> None:
        pass
