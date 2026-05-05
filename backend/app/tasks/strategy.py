from __future__ import annotations

import asyncio
import importlib
import logging

import redis.asyncio as aioredis

from app.core.celery_app import celery_app
from app.core.settings import settings
from app.services.data_fetcher import TickData
from app.services.strategy_executer import StrategyExecuter
from app.services.trade_adapter.paper import PaperTradeAdapter
from app.services.trade_executer import TradeExecuter

logger = logging.getLogger(__name__)

_LOCK_TIMEOUT = 60


@celery_app.task(name="app.tasks.strategy.run_strategy", bind=True)
def run_strategy(self, strategy_id: str, strategy_class_path: str, tick_dict: dict, params: dict | None = None) -> str:
    """
    Execute one strategy for one tick.

    strategy_class_path: fully qualified class path, e.g. "strategies.mbml.MBMLStrategy"
    Releases the Redis lock when done.
    """
    async def run() -> str:
        r = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        lock_key = f"strategy_lock:{strategy_id}"
        try:
            tick = TickData(**tick_dict)

            # Dynamic import so strategies can live anywhere
            module_path, class_name = strategy_class_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            strategy_cls: type[StrategyExecuter] = getattr(module, class_name)

            strategy = strategy_cls(params=params)
            signal = await strategy.execute(tick)

            if signal:
                adapter = PaperTradeAdapter()
                executer = TradeExecuter(adapter=adapter, strategy_id=strategy_id)
                await executer.execute(signal)
                return f"Signal {signal.side.value} executed for {signal.asset_slug}"

            return "No signal"

        except Exception as exc:
            logger.exception(f"Strategy {strategy_id} raised: {exc}")
            raise
        finally:
            await r.delete(lock_key)
            await r.aclose()

    return asyncio.run(run())
