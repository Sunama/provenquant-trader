"""
Example strategy: simple RSI mean-reversion.

Register it via CLI:
    python tasks.py start-trader --strategy strategies.example_rsi.RSIStrategy

Or programmatically:
    trader.register_strategy(RSIStrategy)
"""
from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np

from app.services.data_fetcher import Subscription, TickData
from app.services.strategy_executer import StrategyExecuter, TradeSignal, SignalSide


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
    """
    Go long when RSI(14) < 30, short when RSI(14) > 70.
    TP = 2%, SL = 1%, uses 50% of available balance per trade.
    """

    RSI_PERIOD = 14
    OVERSOLD = 30
    OVERBOUGHT = 70

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params)
        # Deque is process-local — for cross-invocation state use Redis.
        self._closes: deque[float] = deque(maxlen=self.RSI_PERIOD + 10)

    @property
    def id(self) -> str:
        return "rsi_btcusdt_30m"

    @property
    def subscriptions(self) -> list[Subscription]:
        return [Subscription(asset_slug="btcusdt", timeframe="30m", exchange="binance", is_trigger=True)]

    async def execute(self, tick: TickData) -> Optional[TradeSignal]:
        self._closes.append(tick.close)
        rsi = _rsi(list(self._closes), self.RSI_PERIOD)

        if rsi < self.OVERSOLD:
            return TradeSignal(
                side=SignalSide.LONG,
                asset_slug=tick.asset_slug,
                timeframe=tick.timeframe,
                price=tick.close,
                tp_pct=0.02,
                sl_pct=0.01,
                size_pct=0.5,
            )
        if rsi > self.OVERBOUGHT:
            return TradeSignal(
                side=SignalSide.SHORT,
                asset_slug=tick.asset_slug,
                timeframe=tick.timeframe,
                price=tick.close,
                tp_pct=0.02,
                sl_pct=0.01,
                size_pct=0.5,
            )
        return None
