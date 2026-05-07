from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select, desc

from app.db.models.tick import Tick
from app.db.models.funding_rate import FundingRate
from app.db.models.mark_price import MarkPrice
from app.db.models.open_interest import OpenInterest
from app.db.session import SessionLocal
from app.services.data_fetcher import OrderBookData

logger = logging.getLogger(__name__)


class InternalDataFetcher:
    """
    Provides historical market data from Postgres for use inside StrategyExecuter.execute().
    Strategies can instantiate this directly; it uses async SQLAlchemy sessions.

    Example usage inside a strategy:
        fetcher = InternalDataFetcher()
        klines = await fetcher.get_klines("btcusdt", "1h", limit=200)
    """

    async def get_klines(
        self,
        asset_slug: str,
        timeframe: str,
        exchange: str = "binance",
        limit: int = 200,
        before: Optional[datetime] = None,
    ) -> list[Tick]:
        async with SessionLocal() as session:
            stmt = (
                select(Tick)
                .where(
                    Tick.asset_slug == asset_slug,
                    Tick.timeframe == timeframe,
                )
                .order_by(desc(Tick.time))
                .limit(limit)
            )
            if before:
                stmt = stmt.where(Tick.time < before)
            result = await session.execute(stmt)
            rows = result.scalars().all()
        return list(reversed(rows))  # oldest first

    async def get_funding_rates(
        self,
        asset_slug: str,
        exchange: str = "binance",
        limit: int = 50,
    ) -> list[FundingRate]:
        async with SessionLocal() as session:
            result = await session.execute(
                select(FundingRate)
                .where(FundingRate.asset_slug == asset_slug, FundingRate.exchange == exchange)
                .order_by(desc(FundingRate.time))
                .limit(limit)
            )
            rows = result.scalars().all()
        return list(reversed(rows))

    async def get_mark_prices(
        self,
        asset_slug: str,
        exchange: str = "binance",
        market_type: str = "futures",
        limit: int = 200,
    ) -> list[MarkPrice]:
        async with SessionLocal() as session:
            result = await session.execute(
                select(MarkPrice)
                .where(
                    MarkPrice.asset_slug == asset_slug,
                    MarkPrice.exchange == exchange,
                    MarkPrice.market_type == market_type,
                )
                .order_by(desc(MarkPrice.time))
                .limit(limit)
            )
            rows = result.scalars().all()
        return list(reversed(rows))

    async def get_open_interest(
        self,
        asset_slug: str,
        exchange: str = "binance",
        limit: int = 50,
    ) -> list[OpenInterest]:
        async with SessionLocal() as session:
            result = await session.execute(
                select(OpenInterest)
                .where(OpenInterest.asset_slug == asset_slug, OpenInterest.exchange == exchange)
                .order_by(desc(OpenInterest.time))
                .limit(limit)
            )
            rows = result.scalars().all()
        return list(reversed(rows))

    async def get_orderbook(
        self,
        asset_slug: str,
        exchange: str = "binance",
    ) -> Optional[OrderBookData]:
        """Returns latest order book snapshot from Redis (not persisted to Postgres)."""
        import redis.asyncio as aioredis
        from app.core.settings import settings

        r = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            key = f"orderbook:{asset_slug}:{exchange}"
            raw = await r.get(key)
            if not raw:
                return None
            data = json.loads(raw)
            return OrderBookData(
                asset_slug=asset_slug,
                exchange=exchange,
                time=data.get("time", 0),
                bids=data.get("bids", []),
                asks=data.get("asks", []),
            )
        finally:
            await r.aclose()
