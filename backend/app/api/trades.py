from fastapi import APIRouter
from app.services.trade_adapter.paper import PaperTradeAdapter
import asyncio

router = APIRouter()


@router.get("/balance")
async def get_balance():
    adapter = PaperTradeAdapter()
    balance = await adapter.get_balance()
    return {"balance": balance}


@router.get("/position/{symbol}")
async def get_position(symbol: str):
    adapter = PaperTradeAdapter()
    pos = await adapter.get_open_position(symbol)
    if not pos:
        return {"open": False}
    return {
        "open": True,
        "symbol": pos.symbol,
        "side": pos.side,
        "size": pos.size,
        "entry_price": pos.entry_price,
    }
