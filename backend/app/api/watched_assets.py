from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.models.watched_asset import WatchedAsset
from app.db.session import SessionLocal
from app.services.symbol_validator import validate_symbol

router = APIRouter()


async def get_db():
    async with SessionLocal() as db:
        yield db


class WatchedAssetCreate(BaseModel):
    symbol: str
    exchange: str
    market_type: str
    enabled: bool = True
    timeframes: list[str]


class WatchedAssetUpdate(BaseModel):
    symbol: str | None = None
    exchange: str | None = None
    market_type: str | None = None
    enabled: bool | None = None
    timeframes: list[str] | None = None


def _serialize(w: WatchedAsset) -> dict:
    return {
        "id": w.id,
        "symbol": w.symbol,
        "exchange": w.exchange,
        "market_type": w.market_type,
        "enabled": w.enabled,
        "timeframes": w.timeframes,
        "base_asset": w.base_asset,
        "quote_asset": w.quote_asset,
    }


@router.get("/")
async def list_watched_assets(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WatchedAsset))
    return [_serialize(w) for w in result.scalars().all()]


@router.post("/", status_code=201)
async def create_watched_asset(body: WatchedAssetCreate, db: AsyncSession = Depends(get_db)):
    info = await validate_symbol(body.symbol, body.exchange, body.market_type)
    if info is None:
        raise HTTPException(
            status_code=422,
            detail=f"Symbol '{body.symbol}' not found on {body.exchange} {body.market_type}",
        )
    asset = WatchedAsset(
        symbol=body.symbol,
        exchange=body.exchange,
        market_type=body.market_type,
        enabled=body.enabled,
        timeframes=body.timeframes,
        base_asset=info.base_asset,
        quote_asset=info.quote_asset,
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return _serialize(asset)


@router.put("/{asset_id}")
async def update_watched_asset(asset_id: int, body: WatchedAssetUpdate, db: AsyncSession = Depends(get_db)):
    asset = await db.get(WatchedAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Not found")

    symbol = body.symbol or asset.symbol
    exchange = body.exchange or asset.exchange
    market_type = body.market_type or asset.market_type

    if body.symbol or body.exchange or body.market_type:
        info = await validate_symbol(symbol, exchange, market_type)
        if info is None:
            raise HTTPException(
                status_code=422,
                detail=f"Symbol '{symbol}' not found on {exchange} {market_type}",
            )
        asset.symbol = info.symbol
        asset.exchange = exchange
        asset.market_type = market_type
        asset.base_asset = info.base_asset
        asset.quote_asset = info.quote_asset

    if body.enabled is not None:
        asset.enabled = body.enabled
    if body.timeframes is not None:
        asset.timeframes = body.timeframes

    await db.commit()
    await db.refresh(asset)
    return _serialize(asset)


@router.delete("/{asset_id}", status_code=204)
async def delete_watched_asset(asset_id: int, db: AsyncSession = Depends(get_db)):
    asset = await db.get(WatchedAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(asset)
    await db.commit()
