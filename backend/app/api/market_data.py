from __future__ import annotations

import json
from typing import Optional

import redis.asyncio as aioredis
from fastapi import APIRouter, Query

from app.core.settings import settings
from app.services.internal_data_fetcher import InternalDataFetcher

router = APIRouter()
_fetcher = InternalDataFetcher()


@router.get("/klines")
async def get_klines(
    asset_slug: str,
    timeframe: str,
    exchange: str = "binance",
    limit: int = Query(default=200, le=1000),
):
    ticks = await _fetcher.get_klines(asset_slug, timeframe, exchange, limit)
    return [
        {
            "time": int(t.time.timestamp() * 1000),
            "open": t.open, "high": t.high,
            "low": t.low, "close": t.close,
            "volume": t.volume,
        }
        for t in ticks
    ]


@router.get("/funding-rates")
async def get_funding_rates(
    asset_slug: str,
    exchange: str = "binance",
    limit: int = Query(default=50, le=200),
):
    rows = await _fetcher.get_funding_rates(asset_slug, exchange, limit)
    return [
        {"time": int(r.time.timestamp() * 1000), "rate": r.rate}
        for r in rows
    ]


@router.get("/mark-prices")
async def get_mark_prices(
    asset_slug: str,
    exchange: str = "binance",
    market_type: str = "futures",
    limit: int = Query(default=200, le=1000),
):
    rows = await _fetcher.get_mark_prices(asset_slug, exchange, market_type, limit)
    return [
        {"time": int(r.time.timestamp() * 1000), "price": r.price, "index_price": r.index_price}
        for r in rows
    ]


@router.get("/open-interest")
async def get_open_interest(
    asset_slug: str,
    exchange: str = "binance",
    limit: int = Query(default=50, le=200),
):
    rows = await _fetcher.get_open_interest(asset_slug, exchange, limit)
    return [
        {"time": int(r.time.timestamp() * 1000), "oi_contracts": r.oi_contracts, "oi_value": r.oi_value}
        for r in rows
    ]


@router.get("/orderbook")
async def get_orderbook(asset_slug: str, exchange: str = "binance"):
    data = await _fetcher.get_orderbook(asset_slug, exchange)
    if not data:
        return {"bids": [], "asks": [], "time": None}
    return {"bids": data.bids, "asks": data.asks, "time": data.time}
