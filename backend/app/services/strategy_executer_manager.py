from __future__ import annotations

import asyncio
import importlib
import logging
from dataclasses import dataclass
from typing import Type

import redis.asyncio as aioredis
from sqlalchemy import select

from app.core.settings import settings
from app.db.models.strategy_config import StrategyConfig
from app.db.session import SessionLocal
from app.services.data_fetcher import DataFetcher, Subscription, TickCallback, TickData
from app.services.strategy_executer import StrategyExecuter

logger = logging.getLogger(__name__)

_LOCK_TIMEOUT = 60  # seconds — max allowed execution time per strategy tick


@dataclass
class _StrategyEntry:
    cls: Type[StrategyExecuter]
    class_path: str
    params: dict | None

    def probe(self) -> StrategyExecuter:
        """Instantiate to inspect id/subscriptions without executing."""
        return self.cls(params=self.params)


class StrategyExecuterManager:
    """
    Manages the set of active StrategyExecuters.

    Responsibilities:
      1. Load enabled StrategyConfigs from Postgres on startup (and on config change)
      2. Maintain one DataFetcher per exchange, subscribing each to the union of
         subscriptions declared by active strategies on that exchange
      3. On each closed bar, dispatch a Celery task for every strategy whose
         trigger subscription matches the tick, guarded by a Redis lock
      4. Listen on Redis Pub/Sub ("strategy:config_changed") for runtime reloads
    """

    def __init__(self, fetcher_registry: dict[str, Type[DataFetcher]]) -> None:
        self._fetcher_registry = fetcher_registry
        self._fetchers: dict[str, DataFetcher] = {}
        self._registry: dict[str, _StrategyEntry] = {}
        self._redis: aioredis.Redis | None = None
        self._watcher_task: asyncio.Task | None = None

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start(self) -> None:
        self._redis = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        await self._load_from_db()
        await self._sync_fetchers()
        self._watcher_task = asyncio.create_task(self._watch_config_changes())
        logger.info("StrategyExecuterManager started")

    async def stop(self) -> None:
        if self._watcher_task:
            self._watcher_task.cancel()
            try:
                await self._watcher_task
            except asyncio.CancelledError:
                pass

        for fetcher in self._fetchers.values():
            await fetcher.stop()
        self._fetchers.clear()

        if self._redis:
            await self._redis.aclose()
        logger.info("StrategyExecuterManager stopped")

    # ── DB loading ────────────────────────────────────────────────

    async def _load_from_db(self) -> None:
        async with SessionLocal() as session:
            result = await session.execute(
                select(StrategyConfig).where(StrategyConfig.enabled == True)  # noqa: E712
            )
            configs = result.scalars().all()

        new_registry: dict[str, _StrategyEntry] = {}
        for config in configs:
            try:
                module_path, class_name = config.strategy_class.rsplit(".", 1)
                module = importlib.import_module(module_path)
                cls: Type[StrategyExecuter] = getattr(module, class_name)
                entry = _StrategyEntry(cls=cls, class_path=config.strategy_class, params=config.params)
                strategy_id = entry.probe().id
                new_registry[strategy_id] = entry
                logger.info(f"Loaded strategy: {strategy_id} ({config.strategy_class})")
            except Exception:
                logger.exception(f"Failed to load strategy class '{config.strategy_class}', skipping")

        self._registry = new_registry

    # ── Fetcher management ────────────────────────────────────────

    async def _sync_fetchers(self) -> None:
        """Create/update/stop DataFetchers to match current strategy subscriptions."""
        subs_by_exchange: dict[str, list[Subscription]] = {}
        for entry in self._registry.values():
            for sub in entry.probe().subscriptions:
                subs_by_exchange.setdefault(sub.exchange, []).append(sub)

        # Start or update fetchers for exchanges now needed
        for exchange, subs in subs_by_exchange.items():
            if exchange not in self._fetchers:
                if exchange not in self._fetcher_registry:
                    logger.warning(f"No DataFetcher registered for exchange '{exchange}', skipping")
                    continue
                fetcher = self._fetcher_registry[exchange]()
                fetcher.add_callback(self._make_tick_callback(exchange))
                self._fetchers[exchange] = fetcher
                fetcher.set_subscriptions(self._dedupe(subs))
                await fetcher.start()
                logger.info(f"Started DataFetcher for exchange '{exchange}'")
            else:
                self._fetchers[exchange].set_subscriptions(self._dedupe(subs))

        # Stop fetchers for exchanges no longer needed
        stale = set(self._fetchers) - set(subs_by_exchange)
        for exchange in stale:
            await self._fetchers.pop(exchange).stop()
            logger.info(f"Stopped DataFetcher for exchange '{exchange}' (no active strategies)")

    @staticmethod
    def _dedupe(subs: list[Subscription]) -> list[Subscription]:
        seen: dict[str, Subscription] = {}
        for s in subs:
            seen[f"{s.asset_slug}:{s.timeframe}"] = s
        return list(seen.values())

    def _make_tick_callback(self, exchange: str) -> TickCallback:
        async def _on_tick(tick: TickData) -> None:
            await self._dispatch(tick, exchange)
        return _on_tick

    # ── Tick dispatch ─────────────────────────────────────────────

    async def _dispatch(self, tick: TickData, exchange: str) -> None:
        """Called for every closed bar. Dispatches Celery tasks for matching strategies."""
        from app.tasks.strategy import run_strategy  # avoid circular import

        for strategy_id, entry in self._registry.items():
            probe = entry.probe()
            triggered = any(
                s.is_trigger
                and s.exchange == exchange
                and s.asset_slug == tick.asset_slug
                and s.timeframe == tick.timeframe
                for s in probe.subscriptions
            )
            if not triggered:
                continue

            lock_key = f"strategy_lock:{strategy_id}"
            if not await self._try_acquire_lock(lock_key):
                logger.debug(f"Strategy {strategy_id} still running, skipping tick")
                continue

            run_strategy.apply_async(
                args=[strategy_id, entry.class_path, tick.to_dict(), entry.params]
            )

    async def _try_acquire_lock(self, key: str) -> bool:
        if not self._redis:
            return True
        result = await self._redis.set(key, "1", nx=True, ex=_LOCK_TIMEOUT)
        return result is not None

    # ── Config change watcher ─────────────────────────────────────

    async def _watch_config_changes(self) -> None:
        """Subscribe to Redis Pub/Sub and reload strategies when notified."""
        pubsub = self._redis.pubsub()
        await pubsub.subscribe("strategy:config_changed")
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    logger.info("StrategyConfig changed signal received, reloading…")
                    await self._reload()
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe("strategy:config_changed")
            await pubsub.aclose()

    async def _reload(self) -> None:
        await self._load_from_db()
        await self._sync_fetchers()
        logger.info("StrategyExecuterManager reloaded")

    # ── Manual registration (for testing / CLI override) ──────────

    def register(self, strategy_class: Type[StrategyExecuter], params: dict | None = None) -> None:
        class_path = f"{strategy_class.__module__}.{strategy_class.__name__}"
        entry = _StrategyEntry(cls=strategy_class, class_path=class_path, params=params)
        strategy_id = entry.probe().id
        self._registry[strategy_id] = entry
        asyncio.create_task(self._sync_fetchers())
        logger.info(f"Strategy manually registered: {strategy_id}")

    def deregister(self, strategy_id: str) -> None:
        self._registry.pop(strategy_id, None)
        asyncio.create_task(self._sync_fetchers())
        logger.info(f"Strategy deregistered: {strategy_id}")
