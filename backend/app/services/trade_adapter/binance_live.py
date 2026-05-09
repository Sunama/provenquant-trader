from __future__ import annotations

from typing import Optional

from app.services.strategy_executer import PriceMethod
from app.services.trade_adapter import OrderRecord, OrderResult, PositionInfo, TradeAdapter


class BinanceLiveAdapter(TradeAdapter):
    """
    Live trading adapter for Binance (STUB — not yet implemented).

    Intended implementation:
    - Orders placed via Binance REST API (fapi.binance.com for futures)
    - Execution confirmations received via Binance User Data Stream (WebSocket)
    - Pending order state stored in Redis for crash recovery
    - On startup: reconcile open orders from REST API to handle missed events
    """

    def __init__(self, api_key: str, api_secret: str, testnet: bool = False) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._testnet = testnet

    async def get_balance(self) -> float:
        raise NotImplementedError("BinanceLiveAdapter.get_balance is not yet implemented")

    async def get_asset_balance(self, asset: str) -> float:
        raise NotImplementedError("BinanceLiveAdapter.get_asset_balance is not yet implemented")

    async def get_all_balances(self) -> dict[str, float]:
        raise NotImplementedError("BinanceLiveAdapter.get_all_balances is not yet implemented")

    async def open_position(
        self,
        symbol: str,
        side: str,
        size: float,
        price: float,
        tp_price: Optional[float] = None,
        sl_price: Optional[float] = None,
        price_method: PriceMethod = PriceMethod.MARKET,
    ) -> OrderResult:
        raise NotImplementedError("BinanceLiveAdapter.open_position is not yet implemented")

    async def close_position(
        self,
        symbol: str,
        side: str,
        price: float,
        reason: str = "signal",
    ) -> OrderResult:
        raise NotImplementedError("BinanceLiveAdapter.close_position is not yet implemented")

    async def get_open_position(self, symbol: str) -> Optional[PositionInfo]:
        raise NotImplementedError("BinanceLiveAdapter.get_open_position is not yet implemented")

    async def get_order_history(self, symbol: str, limit: int = 50) -> list[OrderRecord]:
        raise NotImplementedError("BinanceLiveAdapter.get_order_history is not yet implemented")
