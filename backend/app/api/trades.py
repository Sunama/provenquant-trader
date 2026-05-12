from fastapi import APIRouter
from app.db.models.strategy_config import StrategyConfig
from app.db.session import SessionLocal
from app.services.trade_adapter.paper import PaperTradeAdapter

router = APIRouter()


@router.get("/balance")
async def get_balance():
    adapter = PaperTradeAdapter()
    balance = await adapter.get_balance()
    return {"balance": balance}


@router.get("/balance/{config_id}")
async def get_all_balances(config_id: str):
    async with SessionLocal() as session:
        config = await session.get(StrategyConfig, config_id)
    initial_assets = {}
    if config and config.params:
        initial_assets = config.params.get("initial_assets", {})
    adapter = PaperTradeAdapter(config_id=config_id, initial_assets=initial_assets)
    balances = await adapter.get_all_balances()
    return {"balances": balances}


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
