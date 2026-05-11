from __future__ import annotations

import asyncio
import importlib
import json
import logging
import time

import redis.asyncio as aioredis

from app.core.celery_app import celery_app
from app.core.settings import settings
from app.services.strategy_context import StrategyContext
from app.services.strategy_executer import ExecutionPlan, StrategyExecuter

logger = logging.getLogger(__name__)

_SIGNAL_STREAM = "signals:trade"
_BROADCAST_STREAM = "signals:broadcast"
_STREAM_MAXLEN = 10000


@celery_app.task(name="app.tasks.strategy.run_strategy", bind=True)
def run_strategy(
    self,
    config_id: str,
    strategy_class_path: str,
    context_dict: dict,
    params: dict | None = None,
) -> str:
    """
    Execute one strategy for one tick.
    ExecutionPlan is published to Redis Streams for TradeExecuterProcess to consume.
    Releases the Redis lock on completion (success or failure).
    """
    logger.info(f"Starting run_strategy task for config_id={config_id} with strategy {strategy_class_path}")
    async def run() -> str:
        r = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        lock_key = f"strategy_lock:{config_id}"
        try:
            logger.info(f"Attempting to run strategy {config_id} with class {strategy_class_path}")
            context = StrategyContext.from_dict(context_dict)

            module_path, class_name = strategy_class_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            strategy_cls: type[StrategyExecuter] = getattr(module, class_name)

            strategy = strategy_cls(
                params=params,
                legs=context.legs,
                config_id=config_id,
            )
            plan: ExecutionPlan | None = await strategy.execute(context)

            if plan is None or not plan.orders:
                return "No signal"

            await _publish_plan(r, plan, config_id, context)
            return f"{len(plan.orders)} order(s) published for config_id={config_id}"

        except Exception as exc:
            logger.exception(f"Strategy config_id={config_id} raised: {exc}")
            raise
        finally:
            await r.delete(lock_key)
            await r.aclose()

    return asyncio.run(run())


async def _publish_plan(
    r: aioredis.Redis,
    plan: ExecutionPlan,
    config_id: str,
    context: StrategyContext,
) -> None:
    ts = str(time.time())
    tick = context.tick
    base_fields = {
        "config_id": config_id,
        "strategy_id": config_id,  # kept for backward compat with TradeExecuterProcess reader
        "ts": ts,
        "tick_symbol": tick.symbol,
        "tick_timeframe": tick.timeframe,
        "tick_market_type": tick.market_type,
        "tick_close": str(tick.close),
        "tick_time": str(tick.time),
        "on_complete": plan.on_complete or "",
        "plan_metadata": json.dumps(plan.metadata),
        "orders": json.dumps([o.to_dict() for o in plan.orders]),
    }
    await r.xadd(_SIGNAL_STREAM, base_fields, maxlen=_STREAM_MAXLEN)
    await r.xadd(_BROADCAST_STREAM, base_fields, maxlen=_STREAM_MAXLEN)

