from __future__ import annotations

import logging

import httpx

from app.core.settings import settings
from app.services.data_collector import DataCollector

logger = logging.getLogger(__name__)


class ProvenQuantDataCollector(DataCollector):
    """
    Extends DefaultDataCollector: after flushing ticks to local Postgres,
    also forwards the tick count / status to the ProvenQuant main API.

    If PROVENQUANT_API_URL or PROVENQUANT_API_KEY is empty, forwarding is skipped silently.
    """

    async def after_collect(self, tick_count: int) -> None:
        if not settings.PROVENQUANT_API_URL or not settings.PROVENQUANT_API_KEY:
            return

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"{settings.PROVENQUANT_API_URL}/api/trader/heartbeat",
                    headers={"X-API-Key": settings.PROVENQUANT_API_KEY},
                    json={"tick_count": tick_count},
                )
        except Exception:
            logger.warning("Failed to forward heartbeat to ProvenQuant API", exc_info=True)
