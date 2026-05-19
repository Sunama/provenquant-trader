from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.models.position import Position
from app.db.models.strategy_asset import StrategyAsset
from app.db.models.strategy_config import StrategyConfig
from app.db.models.trade_history import TradeHistory
from app.db.session import SessionLocal
from app.services.trade_adapter.paper import PaperTradeAdapter

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
        "tp_price": r.tp_price,
        "sl_price": r.sl_price,
        "exit_price": r.exit_price,
        "exit_time": r.exit_time.isoformat() if r.exit_time else None,
        "entry_reason": r.entry_reason,
        "exit_reason": r.exit_reason,
        "pnl": r.pnl,
        "pnl_pct": r.pnl_pct,
        "is_open": r.is_open,
        "leverage": r.leverage,
        "market_type": r.market_type,
        "timeout": r.timeout.isoformat() if r.timeout else None,
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
        raise HTTPException(status_code=404, detail="Not found")
    return _serialize(pos)


class CloseBody(BaseModel):
    price: float


@router.post("/{position_id}/close")
async def close_position_manual(
    position_id: int,
    body: CloseBody,
    db: AsyncSession = Depends(get_db),
):
    pos = await db.get(Position, position_id)
    if not pos or not pos.is_open:
        raise HTTPException(status_code=404, detail="Position not found or already closed")

    config = await db.get(StrategyConfig, pos.strategy_id)
    initial_assets = (config.params or {}).get("initial_assets", {}) if config else {}

    stmt = (
        select(StrategyAsset)
        .where(
            StrategyAsset.strategy_id == pos.strategy_id,
            StrategyAsset.symbol == pos.symbol,
        )
        .limit(1)
    )
    asset = (await db.execute(stmt)).scalar_one_or_none()
    base_asset = asset.base_asset if asset else ""
    quote_asset = asset.quote_asset if asset else "USDT"

    adapter = PaperTradeAdapter(config_id=pos.strategy_id, initial_assets=initial_assets)
    result = await adapter.close_position(pos.symbol, pos.side, body.price, "Manual Close Position")

    is_long = pos.side == "long"
    gross_pnl = (
        (result.price - pos.entry_price) * pos.size
        if is_long
        else (pos.entry_price - result.price) * pos.size
    )
    close_cost = result.price * result.size
    transaction_fee = asset.transaction_fee if asset else 0.0
    fee = close_cost * transaction_fee

    pos.exit_price = result.price
    pos.exit_time = datetime.now(timezone.utc)
    pos.exit_reason = "Manual Close Position"
    pos.is_open = False
    pos.timeout = None
    pos.pnl = gross_pnl - fee
    pos.pnl_pct = pos.pnl / (pos.entry_price * pos.size) if pos.entry_price and pos.size else 0

    close_trade_type = "close_long" if is_long else "close_short"
    th = TradeHistory(
        strategy_id=pos.strategy_id,
        occurred_at=datetime.now(timezone.utc),
        trade_type=close_trade_type,
        symbol=pos.symbol,
        base_asset=base_asset,
        quote_asset=quote_asset,
        bought_asset=quote_asset if is_long else base_asset,
        sold_asset=base_asset if is_long else quote_asset,
        bought_qty=close_cost if is_long else result.size,
        sold_qty=result.size if is_long else close_cost,
        exchange_rate=result.price,
        fee=fee,
        fee_asset=quote_asset,
        exchange="paper",
        market_type=pos.market_type,
        leverage=pos.leverage,
        reason="Manual Close Position",
    )
    db.add(th)
    await db.commit()
    await db.refresh(pos)
    return _serialize(pos)
