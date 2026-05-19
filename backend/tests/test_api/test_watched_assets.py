"""
API tests for /api/watched-assets endpoints.
validate_symbol is mocked to avoid real Binance API calls.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.db.models.watched_asset import WatchedAsset
from tests.test_api.conftest import needs_db

pytestmark = [pytest.mark.integration, needs_db]

_VALIDATE_PATCH = "app.api.watched_assets.validate_symbol"

_BTC_BODY = {
    "symbol": "BTCUSDT",
    "exchange": "binance",
    "market_type": "futures",
    "enabled": True,
    "timeframes": ["15m", "1h"],
}


def _mock_symbol_info(symbol="BTCUSDT", base="BTC", quote="USDT",
                       exchange="binance", market_type="futures"):
    from app.services.symbol_validator import SymbolInfo
    return SymbolInfo(symbol=symbol, base_asset=base, quote_asset=quote,
                      exchange=exchange, market_type=market_type)


# ── GET /api/watched-assets/ ─────────────────────────────────────────────────

async def test_list_watched_assets_empty(client):
    r = await client.get("/api/watched-assets/")
    assert r.status_code == 200
    assert r.json() == []


async def test_list_watched_assets_returns_all(client, db):
    db.add(WatchedAsset(
        symbol="BTCUSDT", exchange="binance", market_type="futures",
        enabled=True, timeframes=["1h"], base_asset="BTC", quote_asset="USDT",
    ))
    db.add(WatchedAsset(
        symbol="ETHUSDT", exchange="binance", market_type="spot",
        enabled=True, timeframes=["30m"], base_asset="ETH", quote_asset="USDT",
    ))
    await db.commit()

    r = await client.get("/api/watched-assets/")
    assert r.status_code == 200
    assert len(r.json()) == 2


# ── POST /api/watched-assets/ ────────────────────────────────────────────────

async def test_create_watched_asset(client):
    with patch(_VALIDATE_PATCH, new_callable=AsyncMock, return_value=_mock_symbol_info()):
        r = await client.post("/api/watched-assets/", json=_BTC_BODY)

    assert r.status_code == 201
    data = r.json()
    assert data["symbol"] == "BTCUSDT"
    assert data["base_asset"] == "BTC"
    assert data["quote_asset"] == "USDT"
    assert data["timeframes"] == ["15m", "1h"]


async def test_create_watched_asset_invalid_symbol_returns_422(client):
    with patch(_VALIDATE_PATCH, new_callable=AsyncMock, return_value=None):
        r = await client.post("/api/watched-assets/", json={**_BTC_BODY, "symbol": "INVALID"})

    assert r.status_code == 422


async def test_create_watched_asset_response_schema(client):
    with patch(_VALIDATE_PATCH, new_callable=AsyncMock, return_value=_mock_symbol_info()):
        r = await client.post("/api/watched-assets/", json=_BTC_BODY)

    assert r.status_code == 201
    data = r.json()
    for field in ("id", "symbol", "exchange", "market_type", "enabled", "timeframes",
                  "base_asset", "quote_asset"):
        assert field in data


# ── PUT /api/watched-assets/{id} ─────────────────────────────────────────────

async def test_update_watched_asset_timeframes(client, db):
    asset = WatchedAsset(
        symbol="BTCUSDT", exchange="binance", market_type="futures",
        enabled=True, timeframes=["1h"], base_asset="BTC", quote_asset="USDT",
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)

    r = await client.put(
        f"/api/watched-assets/{asset.id}",
        json={"timeframes": ["5m", "15m", "1h"]},
    )
    assert r.status_code == 200
    assert r.json()["timeframes"] == ["5m", "15m", "1h"]


async def test_update_watched_asset_enabled_flag(client, db):
    asset = WatchedAsset(
        symbol="BTCUSDT", exchange="binance", market_type="futures",
        enabled=True, timeframes=["1h"], base_asset="BTC", quote_asset="USDT",
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)

    r = await client.put(f"/api/watched-assets/{asset.id}", json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["enabled"] is False


async def test_update_watched_asset_not_found(client):
    r = await client.put("/api/watched-assets/9999", json={"enabled": False})
    assert r.status_code == 404


# ── DELETE /api/watched-assets/{id} ──────────────────────────────────────────

async def test_delete_watched_asset(client, db):
    asset = WatchedAsset(
        symbol="BTCUSDT", exchange="binance", market_type="futures",
        enabled=True, timeframes=["1h"], base_asset="BTC", quote_asset="USDT",
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)

    r = await client.delete(f"/api/watched-assets/{asset.id}")
    assert r.status_code == 204

    # Verify it's gone from the list
    r2 = await client.get("/api/watched-assets/")
    assert r2.json() == []


async def test_delete_watched_asset_not_found(client):
    r = await client.delete("/api/watched-assets/9999")
    assert r.status_code == 404
