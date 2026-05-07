from __future__ import annotations

from sqlalchemy import select

from app.db.models.watched_asset import WatchedAsset
from app.db.session import SessionLocal
from app.services.data_fetcher import Subscription


class WatchedAssetManager:
    """
    Reads WatchedAsset records from DB and converts them to Subscription objects
    for the DataFetcher to subscribe to — independent of active strategies.
    """

    async def get_subscriptions(self) -> list[Subscription]:
        async with SessionLocal() as session:
            result = await session.execute(
                select(WatchedAsset).where(WatchedAsset.enabled == True)  # noqa: E712
            )
            watched = result.scalars().all()

        subscriptions: list[Subscription] = []
        for asset in watched:
            for timeframe in (asset.timeframes or []):
                subscriptions.append(
                    Subscription(
                        asset_slug=asset.asset_slug,
                        exchange=asset.exchange,
                        timeframe=timeframe,
                        market_type=asset.market_type,
                        tick_process=False,  # watched assets never trigger strategy execution
                    )
                )
        return subscriptions
