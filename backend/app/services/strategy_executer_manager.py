from __future__ import annotations

import asyncio
import importlib
import logging
import time
from dataclasses import dataclass
from typing import Type

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.settings import settings
import app.db.base  # noqa: F401 — registers all ORM models so relationships resolve
from app.db.models.strategy_config import StrategyConfig
from app.db.session import SessionLocal
from app.services.data_fetcher import DataFetcher, Subscription, TickCallback, TickData
from app.services.strategy_executer import StrategyExecuter, StrategyAssetConfig

logger = logging.getLogger(__name__)

_LOCK_TIMEOUT = 60  # seconds — max allowed execution time per strategy tick


@dataclass
class _StrategyEntry:
    config_id: str
    cls: Type[StrategyExecuter]
    class_path: str
    params: dict | None
    assets: list[StrategyAssetConfig]
    is_paper: bool = True

    def probe(self) -> StrategyExecuter:
        return self.cls(params=self.params, assets=self.assets)


class StrategyExecuterManager:
    """
    Manages the set of active StrategyExecuters.

    Responsibilities:
      1. Load enabled StrategyConfigs + their assets from Postgres on startup
      2. Maintain one DataFetcher per exchange, subscribing to the union of all
         strategy asset subscriptions plus WatchedAsset subscriptions
      3. On each closed bar, dispatch a Celery task for every strategy whose
         tick_process subscription matches — guarded by a Redis lock
      4. Publish trade signals to Redis Stream "signals:trade" (read by TradeExecuterProcess)
      5. Listen on Redis Pub/Sub "strategy:config_changed" for runtime reloads
    """

    def __init__(self, fetcher_registry: dict[str, dict[str, Type[DataFetcher]]]) -> None:
        self._fetcher_registry = fetcher_registry
        self._fetchers: dict[str, DataFetcher] = {}
        self._registry: dict[str, _StrategyEntry] = {}   # strategy_id → entry
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
                select(StrategyConfig)
                .where(StrategyConfig.enabled == True)  # noqa: E712
                .options(selectinload(StrategyConfig.assets))
            )
            configs = result.scalars().all()

        new_registry: dict[str, _StrategyEntry] = {}
        for config in configs:
            try:
                module_path, class_name = config.strategy_class.rsplit(".", 1)
                module = importlib.import_module(module_path)
                cls: Type[StrategyExecuter] = getattr(module, class_name)

                asset_configs = [
                    StrategyAssetConfig(
                        asset_num=a.asset_num,
                        asset_slug=a.asset_slug,
                        exchange=a.exchange,
                        timeframe=a.timeframe,
                        market_type=a.market_type,
                        tick_process=a.tick_process,
                    )
                    for a in sorted(config.assets, key=lambda x: x.asset_num)
                ]

                entry = _StrategyEntry(
                    config_id=config.id,
                    cls=cls,
                    class_path=config.strategy_class,
                    params=config.params,
                    assets=asset_configs,
                    is_paper=config.is_paper,
                )
                new_registry[config.id] = entry
                logger.info(f"Loaded strategy: {config.id} ({config.strategy_class}) with {len(asset_configs)} asset(s)")
            except Exception:
                logger.exception(f"Failed to load strategy class '{config.strategy_class}', skipping")

        self._registry = new_registry

    # ── Fetcher management ────────────────────────────────────────

    async def _sync_fetchers(self) -> None:
        """Create/update/stop DataFetchers to match current strategy + watched subscriptions.

        Fetchers are keyed by "{exchange}:{market_type}:{'paper'|'live'}" so that paper
        strategies connect to Binance testnet and live strategies connect to mainnet.
        """
        grouped: dict[str, list[Subscription]] = {}
        meta: dict[str, tuple[str, str, bool]] = {}  # key → (exchange, market_type, is_paper)

        for entry in self._registry.values():
            for sub in entry.probe().subscriptions:
                mode = "paper" if entry.is_paper else "live"
                key = f"{sub.exchange}:{sub.market_type}:{mode}"
                grouped.setdefault(key, []).append(sub)
                meta[key] = (sub.exchange, sub.market_type, entry.is_paper)

        # WatchedAssets always use live (mainnet) connections
        try:
            from app.services.watched_asset_manager import WatchedAssetManager
            for sub in await WatchedAssetManager().get_subscriptions():
                key = f"{sub.exchange}:{sub.market_type}:live"
                grouped.setdefault(key, []).append(sub)
                meta[key] = (sub.exchange, sub.market_type, False)
        except Exception:
            logger.debug("WatchedAssetManager not available or empty")

        for key, subs in grouped.items():
            exchange, market_type, is_paper = meta[key]
            if key not in self._fetchers:
                cls = self._fetcher_registry.get(exchange, {}).get(market_type)
                if cls is None:
                    logger.warning(f"No DataFetcher for '{exchange}:{market_type}', skipping")
                    continue
                fetcher = cls(testnet=is_paper)
                fetcher.add_callback(self._make_tick_callback(exchange))
                self._fetchers[key] = fetcher
                fetcher.set_subscriptions(self._dedupe(subs))
                await fetcher.start()
                logger.info(f"Started DataFetcher '{key}' (testnet={is_paper})")
            else:
                self._fetchers[key].set_subscriptions(self._dedupe(subs))

        stale = set(self._fetchers) - set(grouped)
        for key in stale:
            await self._fetchers.pop(key).stop()
            logger.info(f"Stopped DataFetcher '{key}' (no active strategies)")

    @staticmethod
    def _dedupe(subs: list[Subscription]) -> list[Subscription]:
        seen: dict[str, Subscription] = {}
        for s in subs:
            key = f"{s.asset_slug}:{s.timeframe}:{s.market_type}"
            seen[key] = s
        return list(seen.values())

    def _make_tick_callback(self, exchange: str) -> TickCallback:
        # exchange arg kept for interface compatibility; dispatch matches on asset_slug+timeframe
        async def _on_tick(tick: TickData) -> None:
            await self._dispatch(tick, exchange)
        return _on_tick

    # ── Tick dispatch ─────────────────────────────────────────────

    async def _dispatch(self, tick: TickData, exchange: str) -> None:
        """Called for every closed bar. Dispatches Celery tasks for matching strategies."""
        from app.tasks.strategy import run_strategy  # avoid circular import

        for strategy_id, entry in self._registry.items():
            # Find the asset_num of the triggering subscription
            triggered_asset_num: int | None = None
            for asset in entry.assets:
                if (
                    asset.tick_process
                    and asset.exchange == exchange
                    and asset.asset_slug == tick.asset_slug
                    and asset.timeframe == tick.timeframe
                ):
                    triggered_asset_num = asset.asset_num
                    break

            if triggered_asset_num is None:
                continue

            lock_key = f"strategy_lock:{strategy_id}"
            if not await self._try_acquire_lock(lock_key):
                logger.debug(f"Strategy {strategy_id} still running, skipping tick")
                continue

            assets_dicts = [
                {
                    "asset_num": a.asset_num,
                    "asset_slug": a.asset_slug,
                    "exchange": a.exchange,
                    "timeframe": a.timeframe,
                    "market_type": a.market_type,
                    "tick_process": a.tick_process,
                }
                for a in entry.assets
            ]

            run_strategy.apply_async(
                args=[
                    strategy_id,
                    entry.class_path,
                    tick.to_dict(),
                    entry.params,
                    assets_dicts,
                    triggered_asset_num,
                    entry.config_id,
                ]
            )

    async def _try_acquire_lock(self, key: str) -> bool:
        if not self._redis:
            return True
        result = await self._redis.set(key, "1", nx=True, ex=_LOCK_TIMEOUT)
        return result is not None

    # ── Config change watcher ─────────────────────────────────────

    async def _watch_config_changes(self) -> None:
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

    # ── Manual registration (for testing / CLI) ───────────────────

    def register(
        self,
        strategy_class: Type[StrategyExecuter],
        params: dict | None = None,
        assets: list[StrategyAssetConfig] | None = None,
    ) -> None:
        class_path = f"{strategy_class.__module__}.{strategy_class.__name__}"
        entry = _StrategyEntry(
            config_id="manual",
            cls=strategy_class,
            class_path=class_path,
            params=params,
            assets=assets or [],
        )
        strategy_id = entry.probe().id
        self._registry[strategy_id] = entry
        asyncio.create_task(self._sync_fetchers())
        logger.info(f"Strategy manually registered: {strategy_id}")

    def deregister(self, strategy_id: str) -> None:
        self._registry.pop(strategy_id, None)
        asyncio.create_task(self._sync_fetchers())
        logger.info(f"Strategy deregistered: {strategy_id}")
