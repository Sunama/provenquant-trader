from __future__ import annotations

import asyncio
import logging

from app.services.data_fetcher.binance import BinanceFuturesDataFetcher
from app.services.data_fetcher.binance_options import BinanceOptionsDataFetcher
from app.services.data_fetcher.binance_spot import BinanceSpotDataFetcher
from app.services.strategy_executer_manager import StrategyExecuterManager

logger = logging.getLogger(__name__)


class Trader:
    """
    Top-level orchestrator and main process entry point.

    Active strategies are loaded automatically from the StrategyConfig DB table.
    Runtime config changes are picked up via Redis Pub/Sub without restart.

    Usage:
        asyncio.run(Trader().start())
    """

    def __init__(self) -> None:
        self._manager = StrategyExecuterManager({
            "binance": {
                "futures": BinanceFuturesDataFetcher,
                "spot":    BinanceSpotDataFetcher,
                "options": BinanceOptionsDataFetcher,
            },
        })

    async def start(self) -> None:
        logger.info("Trader starting…")
        await self._manager.start()
        logger.info("Trader running")

        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def stop(self) -> None:
        logger.info("Trader stopping…")
        await self._manager.stop()
        logger.info("Trader stopped")
