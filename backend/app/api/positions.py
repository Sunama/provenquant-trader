from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List

from app.db.models.position import Position
from app.db.session import SessionLocal

router = APIRouter()


async def get_db():
    async with SessionLocal() as db:
        yield db


@router.get("/", response_model=List[dict])
async def list_positions(open_only: bool = False, db: AsyncSession = Depends(get_db)):
    stmt = select(Position)
    if open_only:
        stmt = stmt.where(Position.is_open == True)
    stmt = stmt.order_by(Position.created_at.desc()).limit(200)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "strategy_id": r.strategy_id,
            "asset_slug": r.asset_slug,
            "side": r.side,
            "entry_price": r.entry_price,
            "entry_time": r.entry_time,
            "exit_price": r.exit_price,
            "exit_time": r.exit_time,
            "exit_reason": r.exit_reason,
            "pnl": r.pnl,
            "pnl_pct": r.pnl_pct,
            "is_open": r.is_open,
        }
        for r in rows
    ]
