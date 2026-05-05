from fastapi import APIRouter
from app.services.trade_adapter.paper import PaperTradeAdapter
import asyncio

router = APIRouter()


@router.get("/balance")
async def get_balance():
    adapter = PaperTradeAdapter()
    balance = await adapter.get_balance()
    return {"balance": balance}


@router.get("/position/{asset_slug}")
async def get_position(asset_slug: str):
    adapter = PaperTradeAdapter()
    pos = await adapter.get_open_position(asset_slug)
    if not pos:
        return {"open": False}
    return {
        "open": True,
        "asset_slug": pos.asset_slug,
        "side": pos.side,
        "size": pos.size,
        "entry_price": pos.entry_price,
    }
