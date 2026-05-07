from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.models.watched_asset import WatchedAsset
from app.db.session import SessionLocal

router = APIRouter()


async def get_db():
    async with SessionLocal() as db:
        yield db


class WatchedAssetCreate(BaseModel):
    asset_slug: str
    exchange: str
    market_type: str
    enabled: bool = True
    timeframes: list[str]


class WatchedAssetUpdate(BaseModel):
    enabled: bool | None = None
    timeframes: list[str] | None = None


@router.get("/")
async def list_watched_assets(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WatchedAsset))
    return [
        {
            "id": w.id,
            "asset_slug": w.asset_slug,
            "exchange": w.exchange,
            "market_type": w.market_type,
            "enabled": w.enabled,
            "timeframes": w.timeframes,
        }
        for w in result.scalars().all()
    ]


@router.post("/", status_code=201)
async def create_watched_asset(body: WatchedAssetCreate, db: AsyncSession = Depends(get_db)):
    asset = WatchedAsset(**body.model_dump())
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return {"id": asset.id}


@router.put("/{asset_id}")
async def update_watched_asset(asset_id: int, body: WatchedAssetUpdate, db: AsyncSession = Depends(get_db)):
    asset = await db.get(WatchedAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Not found")
    if body.enabled is not None:
        asset.enabled = body.enabled
    if body.timeframes is not None:
        asset.timeframes = body.timeframes
    await db.commit()
    return {"id": asset.id}


@router.delete("/{asset_id}", status_code=204)
async def delete_watched_asset(asset_id: int, db: AsyncSession = Depends(get_db)):
    asset = await db.get(WatchedAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(asset)
    await db.commit()
