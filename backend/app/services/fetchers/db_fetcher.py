from __future__ import annotations

from datetime import datetime
from typing import Optional


from app.db.models.funding_rate import FundingRate
from app.db.models.mark_price import MarkPrice
from app.db.models.open_interest import OpenInterest
from app.db.models.position import Position
from app.db.models.tick import Tick
from app.db.models.trade_history import TradeHistory
from app.services.internal_data_fetcher import InternalDataFetcher

_fetcher = InternalDataFetcher()


class DatabaseDataFetcher:
    """
    Input type 3: Historical market data from Postgres.
    Returns ORM model instances; strategies read .open, .close etc. directly.
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
        return await _fetcher.get_klines(symbol, timeframe, exchange, market_type, limit, before)

    async def get_funding_rates(
        self,
        symbol: str,
        exchange: str = "binance",
        market_type: str = "futures",
        limit: int = 50,
    ) -> list[FundingRate]:
        return await _fetcher.get_funding_rates(symbol, exchange, market_type, limit)

    async def get_mark_prices(
        self,
        symbol: str,
        exchange: str = "binance",
        market_type: str = "futures",
        limit: int = 200,
    ) -> list[MarkPrice]:
        return await _fetcher.get_mark_prices(symbol, exchange, market_type, limit)

    async def get_open_interest(
        self,
        symbol: str,
        exchange: str = "binance",
        market_type: str = "futures",
        limit: int = 50,
    ) -> list[OpenInterest]:
        return await _fetcher.get_open_interest(symbol, exchange, market_type, limit)

    async def get_open_positions(
        self,
        strategy_id: str,
        symbol: Optional[str] = None,
    ) -> list[Position]:
        """
        Fetch currently open positions for this strategy from Postgres.
        Pass context.config_id as strategy_id. Optionally filter by symbol.
        """
        return await _fetcher.get_open_positions(strategy_id, symbol)

    async def get_trade_history(
        self,
        config_id: str,
        symbol: Optional[str] = None,
        trade_type: Optional[str] = None,
        limit: int = 50,
    ) -> list[TradeHistory]:
        """
        Fetch this strategy's trade history from Postgres, newest-first.
        Pass context.config_id as config_id. Use limit=1 to get only the last trade.
        """
        return await _fetcher.get_trade_history(config_id, symbol, trade_type, limit)
