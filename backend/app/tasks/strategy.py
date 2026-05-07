from __future__ import annotations

import asyncio
import importlib
import json
import logging
import time

import redis.asyncio as aioredis

from app.core.celery_app import celery_app
from app.core.settings import settings
from app.services.data_fetcher import TickData
from app.services.strategy_executer import StrategyExecuter, StrategyAssetConfig, TradeSignal

logger = logging.getLogger(__name__)

_SIGNAL_STREAM = "signals:trade"
_BROADCAST_STREAM = "signals:broadcast"
_STREAM_MAXLEN = 10000


@celery_app.task(name="app.tasks.strategy.run_strategy", bind=True)
def run_strategy(
    self,
    strategy_id: str,
    strategy_class_path: str,
    tick_dict: dict,
    params: dict | None = None,
    assets_dicts: list[dict] | None = None,
    asset_num: int = 0,
    config_id: str = "",
) -> str:
    """
    Execute one strategy for one tick.
    Signals are published to Redis Streams for TradeExecuterProcess to consume.
    Releases the Redis lock when done.
    """
    async def run() -> str:
        r = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        lock_key = f"strategy_lock:{strategy_id}"
        try:
            tick = TickData(**tick_dict)

            assets = [
                StrategyAssetConfig(
                    asset_num=a["asset_num"],
                    asset_slug=a["asset_slug"],
                    exchange=a["exchange"],
                    timeframe=a["timeframe"],
                    market_type=a["market_type"],
                    tick_process=a["tick_process"],
                )
                for a in (assets_dicts or [])
            ]

            module_path, class_name = strategy_class_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            strategy_cls: type[StrategyExecuter] = getattr(module, class_name)

            strategy = strategy_cls(params=params, assets=assets)
            signals = await _call_execute(strategy, tick, asset_num)

            if not signals:
                return "No signal"

            await _publish_signals(r, signals, strategy_id, config_id, tick)
            return f"{len(signals)} signal(s) published for {strategy_id}"

        except Exception as exc:
            logger.exception(f"Strategy {strategy_id} raised: {exc}")
            raise
        finally:
            await r.delete(lock_key)
            await r.aclose()

    return asyncio.run(run())


async def _call_execute(
    strategy: StrategyExecuter,
    tick: TickData,
    asset_num: int,
) -> list[TradeSignal]:
    """
    Shim for backward-compatible strategies that still use old execute(tick) -> TradeSignal | None.
    The shim will be removed once all strategies migrate to the new signature.
    """
    if strategy._is_legacy():
        result = await strategy.execute(tick)  # type: ignore[call-arg]
        if result is None:
            return []
        # Wrap old-style single signal into new format
        from app.services.strategy_executer import SignalSide
        old_side = result.side if hasattr(result, "side") else "long"
        execute = SignalSide(old_side) if isinstance(old_side, str) else old_side
        return [
            TradeSignal(
                execute=execute,
                asset_num=0,
                exchange_num=0,
                market_type="futures",
                amount=getattr(result, "size_pct", 1.0),
                tp_pct=getattr(result, "tp_pct", None),
                sl_pct=getattr(result, "sl_pct", None),
                price=getattr(result, "price", None),
                metadata={"asset_slug": getattr(result, "asset_slug", ""), "timeframe": getattr(result, "timeframe", "")},
            )
        ]
    return await strategy.execute(tick, asset_num)


async def _publish_signals(
    r: aioredis.Redis,
    signals: list[TradeSignal],
    strategy_id: str,
    config_id: str,
    tick: TickData,
) -> None:
    ts = str(time.time())
    for sig in signals:
        fields = {
            "strategy_id": strategy_id,
            "config_id": config_id,
            "execute": sig.execute.value,
            "asset_num": str(sig.asset_num),
            "exchange_num": str(sig.exchange_num),
            "market_type": sig.market_type,
            "amount": str(sig.amount),
            "tp_pct": str(sig.tp_pct) if sig.tp_pct is not None else "",
            "sl_pct": str(sig.sl_pct) if sig.sl_pct is not None else "",
            "price": str(sig.price) if sig.price is not None else str(tick.close),
            "metadata": json.dumps(sig.metadata),
            "ts": ts,
        }
        await r.xadd(_SIGNAL_STREAM, fields, maxlen=_STREAM_MAXLEN)
        await r.xadd(_BROADCAST_STREAM, fields, maxlen=_STREAM_MAXLEN)
