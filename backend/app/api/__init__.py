from fastapi import APIRouter
from app.api import trades, positions, strategies

api_router = APIRouter()
api_router.include_router(trades.router, prefix="/trades", tags=["trades"])
api_router.include_router(positions.router, prefix="/positions", tags=["positions"])
api_router.include_router(strategies.router, prefix="/strategies", tags=["strategies"])
