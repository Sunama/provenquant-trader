from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel

from app.db.models.strategy_config import StrategyConfig
from app.db.session import SessionLocal

router = APIRouter()


async def get_db():
    async with SessionLocal() as db:
        yield db


class StrategyConfigCreate(BaseModel):
    id: str
    strategy_class: str
    asset_slug: str
    timeframe: str
    params: dict = {}


@router.get("/")
async def list_strategies(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(StrategyConfig))).scalars().all()
    return [
        {
            "id": r.id,
            "strategy_class": r.strategy_class,
            "asset_slug": r.asset_slug,
            "timeframe": r.timeframe,
            "enabled": r.enabled,
            "params": r.params,
        }
        for r in rows
    ]


@router.post("/", status_code=201)
async def create_strategy(body: StrategyConfigCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.get(StrategyConfig, body.id)
    if existing:
        raise HTTPException(status_code=409, detail="Strategy ID already exists")
    cfg = StrategyConfig(**body.model_dump())
    db.add(cfg)
    await db.commit()
    return {"id": cfg.id}


@router.delete("/{strategy_id}", status_code=204)
async def delete_strategy(strategy_id: str, db: AsyncSession = Depends(get_db)):
    cfg = await db.get(StrategyConfig, strategy_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(cfg)
    await db.commit()
