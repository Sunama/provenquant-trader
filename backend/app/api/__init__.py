from fastapi import APIRouter
from app.api import trades, positions, strategies, exchange_accounts, watched_assets, market_data, settings, ws

api_router = APIRouter()
api_router.include_router(trades.router, prefix="/trades", tags=["trades"])
api_router.include_router(positions.router, prefix="/positions", tags=["positions"])
api_router.include_router(strategies.router, prefix="/strategies", tags=["strategies"])
api_router.include_router(exchange_accounts.router, prefix="/exchange-accounts", tags=["exchange-accounts"])
api_router.include_router(watched_assets.router, prefix="/watched-assets", tags=["watched-assets"])
api_router.include_router(market_data.router, prefix="/market-data", tags=["market-data"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
