from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.models.position import Position
from app.db.session import SessionLocal

router = APIRouter()


async def get_db():
    async with SessionLocal() as db:
        yield db


def _serialize(r: Position) -> dict:
    return {
        "id": r.id,
        "strategy_id": r.strategy_id,
        "symbol": r.symbol,
        "side": r.side,
        "entry_price": r.entry_price,
        "entry_time": r.entry_time.isoformat() if r.entry_time else None,
        "size": r.size,
        "exit_price": r.exit_price,
        "exit_time": r.exit_time.isoformat() if r.exit_time else None,
        "exit_reason": r.exit_reason,
        "pnl": r.pnl,
        "pnl_pct": r.pnl_pct,
        "is_open": r.is_open,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.get("/stats")
async def get_position_stats(
    strategy_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(
        func.count(Position.id).label("total"),
        func.coalesce(func.sum(Position.pnl), 0).label("total_pnl"),
        func.count(case((Position.pnl > 0, 1))).label("wins"),
    ).where(Position.is_open == False)  # noqa: E712

    if strategy_id:
        stmt = stmt.where(Position.strategy_id == strategy_id)

    result = (await db.execute(stmt)).one()
    win_rate = result.wins / result.total if result.total else 0
    return {
        "total_trades": result.total,
        "total_pnl": float(result.total_pnl),
        "win_rate": round(win_rate, 4),
        "wins": result.wins,
    }


@router.get("/")
async def list_positions(
    open_only: bool = False,
    strategy_id: Optional[str] = None,
    limit: int = Query(default=200, le=1000),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Position)
    if open_only:
        stmt = stmt.where(Position.is_open == True)  # noqa: E712
    if strategy_id:
        stmt = stmt.where(Position.strategy_id == strategy_id)
    stmt = stmt.order_by(Position.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [_serialize(r) for r in rows]


@router.get("/{position_id}")
async def get_position(position_id: int, db: AsyncSession = Depends(get_db)):
    pos = await db.get(Position, position_id)
    if not pos:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not found")
    return _serialize(pos)
