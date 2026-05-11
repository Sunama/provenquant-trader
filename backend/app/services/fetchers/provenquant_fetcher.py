from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.settings import settings

logger = logging.getLogger(__name__)


class ProvenQuantDataFetcher:
    """
    Input type 4: Predictions and signals from the ProvenQuant platform API.
    Requires PROVENQUANT_API_URL and PROVENQUANT_API_KEY in settings.
    Returns data as plain dicts; strategies convert to pandas DataFrame if needed.
    """

    def __init__(self) -> None:
        self._base_url = settings.PROVENQUANT_API_URL.rstrip("/")
        self._api_key = settings.PROVENQUANT_API_KEY

    @property
    def available(self) -> bool:
        return bool(self._base_url and self._api_key)

    async def fetch_predictions(self, model_id: str, symbol: str, limit: int = 100) -> list[dict[str, Any]]:
        """Fetch latest model predictions for a symbol."""
        if not self.available:
            logger.warning("ProvenQuantDataFetcher: API URL/key not configured")
            return []
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self._base_url}/api/predictions",
                    headers={"X-API-Key": self._api_key},
                    params={"model_id": model_id, "symbol": symbol, "limit": limit},
                )
            if resp.status_code != 200:
                logger.warning(f"ProvenQuantDataFetcher: HTTP {resp.status_code} for model={model_id}")
                return []
            return resp.json().get("data", [])
        except Exception:
            logger.exception("ProvenQuantDataFetcher: request failed")
            return []

    async def fetch_signals(self, strategy_id: str) -> list[dict[str, Any]]:
        """Fetch active signals for a strategy from the ProvenQuant platform."""
        if not self.available:
            return []
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self._base_url}/api/signals",
                    headers={"X-API-Key": self._api_key},
                    params={"strategy_id": strategy_id},
                )
            if resp.status_code != 200:
                logger.warning(f"ProvenQuantDataFetcher: HTTP {resp.status_code} for signals strategy={strategy_id}")
                return []
            return resp.json().get("data", [])
        except Exception:
            logger.exception("ProvenQuantDataFetcher: signals request failed")
            return []
