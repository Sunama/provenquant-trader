from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.models.trade_history import TradeHistory
from app.db.session import SessionLocal

router = APIRouter()


async def get_db():
    async with SessionLocal() as db:
        yield db


def _serialize(t: TradeHistory) -> dict:
    return {
        "id": t.id,
        "strategy_id": t.strategy_id,
        "occurred_at": t.occurred_at.isoformat(),
        "trade_type": t.trade_type,
        "symbol": t.symbol,
        "base_asset": t.base_asset,
        "quote_asset": t.quote_asset,
        "bought_asset": t.bought_asset,
        "sold_asset": t.sold_asset,
        "bought_qty": t.bought_qty,
        "sold_qty": t.sold_qty,
        "exchange_rate": t.exchange_rate,
        "fee": t.fee,
        "fee_asset": t.fee_asset,
        "exchange": t.exchange,
        "market_type": t.market_type,
        "reason": t.reason,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


@router.get("/")
async def list_trade_history(
    strategy_id: Optional[str] = Query(default=None),
    symbol: Optional[str] = Query(default=None),
    limit: int = Query(default=100, le=1000),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(TradeHistory).order_by(TradeHistory.occurred_at.desc()).limit(limit)
    if strategy_id:
        stmt = stmt.where(TradeHistory.strategy_id == strategy_id)
    if symbol:
        stmt = stmt.where(TradeHistory.symbol == symbol)
    result = await db.execute(stmt)
    return [_serialize(t) for t in result.scalars().all()]
