"""
Example strategy: simple RSI mean-reversion (updated for new multi-asset architecture).

Register via StrategyConfig with:
  strategy_class = "strategies.example_rsi.RSIStrategy"
  assets = [{ asset_slug: "btcusdt", exchange: "binance", timeframe: "30m", market_type: "futures", tick_process: true }]
  params = { "period": 14, "oversold": 30, "overbought": 70, "amount": 0.5 }
"""
from __future__ import annotations

from collections import deque

import numpy as np

from app.services.data_fetcher import Subscription, TickData
from app.services.strategy_executer import (
    ParameterSchema,
    SignalSide,
    StrategyAssetConfig,
    StrategyExecuter,
    TradeSignal,
)


def _rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes[-(period + 1):])
    gains = deltas[deltas > 0].mean() if (deltas > 0).any() else 0.0
    losses = -deltas[deltas < 0].mean() if (deltas < 0).any() else 0.0
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100 - (100 / (1 + rs))


class RSIStrategy(StrategyExecuter):
    """Go long when RSI < oversold threshold, short when RSI > overbought threshold."""

    def __init__(self, params: dict | None = None, assets: list[StrategyAssetConfig] | None = None) -> None:
        super().__init__(params, assets)
        period = self.params.get("period", 14)
        self._closes: deque[float] = deque(maxlen=int(period) + 10)

    @property
    def id(self) -> str:
        return "rsi_btcusdt_30m"

    @property
    def parameter_schema(self) -> list[ParameterSchema]:
        return [
            ParameterSchema(name="period", type="int", default=14, min=2, max=100, description="RSI lookback period"),
            ParameterSchema(name="oversold", type="float", default=30.0, min=10.0, max=50.0, description="RSI oversold threshold → LONG signal"),
            ParameterSchema(name="overbought", type="float", default=70.0, min=50.0, max=90.0, description="RSI overbought threshold → SHORT signal"),
            ParameterSchema(name="amount", type="float", default=0.5, min=0.01, max=1.0, description="Fraction of available balance to use"),
            ParameterSchema(name="tp_pct", type="float", default=0.02, min=0.001, max=0.5, description="Take-profit %"),
            ParameterSchema(name="sl_pct", type="float", default=0.01, min=0.001, max=0.5, description="Stop-loss %"),
        ]

    @property
    def subscriptions(self) -> list[Subscription]:
        # Use configured assets if available; fall back to default
        if self.assets:
            return [
                Subscription(
                    asset_slug=a.asset_slug,
                    timeframe=a.timeframe,
                    exchange=a.exchange,
                    market_type=a.market_type,
                    tick_process=a.tick_process,
                )
                for a in self.assets
            ]
        return [
            Subscription(asset_slug="btcusdt", timeframe="30m", exchange="binance", market_type="futures", tick_process=True)
        ]

    async def execute(self, tick: TickData, asset_num: int = 0) -> list[TradeSignal]:
        period: int = int(self.params.get("period", 14))
        oversold: float = float(self.params.get("oversold", 30.0))
        overbought: float = float(self.params.get("overbought", 70.0))
        amount: float = float(self.params.get("amount", 0.5))
        tp_pct: float = float(self.params.get("tp_pct", 0.02))
        sl_pct: float = float(self.params.get("sl_pct", 0.01))

        self._closes.append(tick.close)
        rsi = _rsi(list(self._closes), period)

        if rsi < oversold:
            return [
                TradeSignal(
                    execute=SignalSide.LONG,
                    asset_num=asset_num,
                    exchange_num=0,
                    market_type="futures",
                    amount=amount,
                    tp_pct=tp_pct,
                    sl_pct=sl_pct,
                    price=tick.close,
                )
            ]
        if rsi > overbought:
            return [
                TradeSignal(
                    execute=SignalSide.SHORT,
                    asset_num=asset_num,
                    exchange_num=0,
                    market_type="futures",
                    amount=amount,
                    tp_pct=tp_pct,
                    sl_pct=sl_pct,
                    price=tick.close,
                )
            ]
        return []
