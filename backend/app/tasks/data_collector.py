import asyncio
import logging

from app.core.celery_app import celery_app
from app.services.data_collector.provenquant import ProvenQuantDataCollector

logger = logging.getLogger(__name__)


@celery_app.task(name="trader.data_collector_polling")
def data_collector_polling() -> str:
    async def run() -> int:
        collector = ProvenQuantDataCollector()
        count = await collector.collect()
        await collector.after_collect(count)
        return count

    count = asyncio.run(run())
    return f"Flushed {count} ticks to Postgres"
