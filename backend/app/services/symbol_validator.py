from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

import httpx
import redis.asyncio as aioredis

from app.core.settings import settings

logger = logging.getLogger(__name__)

_CACHE_TTL = 300  # 5 minutes

_EXCHANGE_INFO_URLS: dict[str, dict[str, str]] = {
    "binance": {
        "spot": "https://api.binance.com/api/v3/exchangeInfo",
        "futures": "https://fapi.binance.com/fapi/v1/exchangeInfo",
        "options": "https://eapi.binance.com/eapi/v1/exchangeInfo",
    }
}


@dataclass
class SymbolInfo:
    symbol: str        # lowercase, e.g. "btcusdt"
    base_asset: str    # e.g. "BTC"
    quote_asset: str   # e.g. "USDT"
    exchange: str
    market_type: str


async def validate_symbol(
    symbol: str,
    exchange: str,
    market_type: str,
) -> Optional[SymbolInfo]:
    """
    Validate a symbol against the exchange REST API.
    Returns SymbolInfo on success, None if the symbol does not exist.
    Results are cached in Redis for 5 minutes to avoid rate-limiting.
    """
    symbol_upper = symbol.upper()
    cache_key = f"syminfo:{exchange}:{market_type}:{symbol_upper}"

    async with aioredis.from_url(settings.REDIS_URL, decode_responses=True) as r:
        cached = await r.get(cache_key)
        if cached:
            try:
                data = json.loads(cached)
                if data is None:
                    return None  # previously confirmed invalid
                return SymbolInfo(**data)
            except Exception:
                pass

    url = _EXCHANGE_INFO_URLS.get(exchange, {}).get(market_type)
    if not url:
        logger.warning(f"No exchange info URL for {exchange}:{market_type}")
        return None

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params={"symbol": symbol_upper})
        if resp.status_code != 200:
            logger.warning(f"[symvalidate] {exchange}:{market_type} {symbol_upper} → HTTP {resp.status_code}")
            await _cache(cache_key, None)
            return None

        body = resp.json()
        # Both spot and futures use the "symbols" array
        symbols_list = body.get("symbols", [body]) if isinstance(body, dict) else [body]
        for s in symbols_list:
            if s.get("symbol", "").upper() == symbol_upper:
                info = SymbolInfo(
                    symbol=symbol.lower(),
                    base_asset=s.get("baseAsset", ""),
                    quote_asset=s.get("quoteAsset", ""),
                    exchange=exchange,
                    market_type=market_type,
                )
                await _cache(cache_key, info)
                return info

        logger.info(f"[symvalidate] {symbol_upper} not found in {exchange}:{market_type}")
        await _cache(cache_key, None)
        return None

    except Exception:
        logger.exception(f"[symvalidate] failed for {symbol_upper}")
        return None


async def _cache(key: str, info: Optional[SymbolInfo]) -> None:
    try:
        async with aioredis.from_url(settings.REDIS_URL, decode_responses=True) as r:
            value = json.dumps(None if info is None else info.__dict__)
            await r.set(key, value, ex=_CACHE_TTL)
    except Exception:
        pass
