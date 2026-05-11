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
    Provides historical market data from Postgres for use inside strategy execute().
    Strategies should use context.db instead of instantiating this directly.
    """

    async def get_klines(
        self,
        symbol: str,
        timeframe: str,
        exchange: str = "binance",
        market_type: str = "futures",
        limit: int = 200,
        before: Optional[datetime] = None,
    ) -> list[Tick]:
        async with SessionLocal() as session:
            stmt = (
                select(Tick)
                .where(
                    Tick.symbol == symbol,
                    Tick.timeframe == timeframe,
                    Tick.market_type == market_type,
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
        symbol: str,
        exchange: str = "binance",
        market_type: str = "futures",
        limit: int = 50,
    ) -> list[FundingRate]:
        async with SessionLocal() as session:
            result = await session.execute(
                select(FundingRate)
                .where(
                    FundingRate.symbol == symbol,
                    FundingRate.exchange == exchange,
                    FundingRate.market_type == market_type,
                )
                .order_by(desc(FundingRate.time))
                .limit(limit)
            )
            rows = result.scalars().all()
        return list(reversed(rows))

    async def get_mark_prices(
        self,
        symbol: str,
        exchange: str = "binance",
        market_type: str = "futures",
        limit: int = 200,
    ) -> list[MarkPrice]:
        async with SessionLocal() as session:
            result = await session.execute(
                select(MarkPrice)
                .where(
                    MarkPrice.symbol == symbol,
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
        symbol: str,
        exchange: str = "binance",
        market_type: str = "futures",
        limit: int = 50,
    ) -> list[OpenInterest]:
        async with SessionLocal() as session:
            result = await session.execute(
                select(OpenInterest)
                .where(
                    OpenInterest.symbol == symbol,
                    OpenInterest.exchange == exchange,
                    OpenInterest.market_type == market_type,
                )
                .order_by(desc(OpenInterest.time))
                .limit(limit)
            )
            rows = result.scalars().all()
        return list(reversed(rows))

    async def get_orderbook(
        self,
        symbol: str,
        exchange: str = "binance",
        market_type: str = "futures",
    ) -> Optional[OrderBookData]:
        """Returns latest order book snapshot from Redis (not persisted to Postgres)."""
        import redis.asyncio as aioredis
        from app.core.settings import settings

        r = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            key = f"orderbook:{symbol}:{exchange}:{market_type}"
            raw = await r.get(key)
            if not raw:
                return None
            data = json.loads(raw)
            return OrderBookData(
                symbol=symbol,
                exchange=exchange,
                time=data.get("time", 0),
                bids=data.get("bids", []),
                asks=data.get("asks", []),
                market_type=market_type,
            )
        finally:
            await r.aclose()
