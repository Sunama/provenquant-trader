"""
Example multi-asset strategy: BTC/ETH pair trading (mean reversion on spread).

Assets required:
  asset_num=0  btcusdt  1h  futures  tick_process=True
  asset_num=1  ethusdt  1h  futures  tick_process=False

Signals:
  When the BTC/ETH ratio deviates > 2 std from rolling mean → enter pair trade:
    LONG BTC (asset_num=0) + SHORT ETH (asset_num=1) when ratio is low
    SHORT BTC + LONG ETH when ratio is high

Register:
    python tasks.py start-trader --strategy strategies.example_pair_trade.PairTradeStrategy
"""
from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np

from app.services.data_fetcher import Subscription, TickData
from app.services.internal_data_fetcher import InternalDataFetcher
from app.services.strategy_executer import (
    ParameterSchema,
    SignalSide,
    StrategyExecuter,
    TradeSignal,
)


class PairTradeStrategy(StrategyExecuter):
    """
    Mean-reversion pair trade on BTC/ETH price ratio.
    Enters when z-score of ratio exceeds threshold.
    """

    @property
    def id(self) -> str:
        return "pair_trade_btc_eth"

    @property
    def parameter_schema(self) -> list[ParameterSchema]:
        return [
            ParameterSchema(name="lookback", type="int", default=20, min=5, max=100, description="Rolling window for mean/std"),
            ParameterSchema(name="z_threshold", type="float", default=2.0, min=1.0, max=4.0, description="Z-score to trigger entry"),
            ParameterSchema(name="amount", type="float", default=0.3, min=0.05, max=0.5, description="Fraction of balance per leg"),
        ]

    @property
    def subscriptions(self) -> list[Subscription]:
        return [
            Subscription(asset_slug="btcusdt", timeframe="1h", exchange="binance", market_type="futures", tick_process=True,
                         description="Primary asset — this tick triggers execution; long when ratio is low"),
            Subscription(asset_slug="ethusdt", timeframe="1h", exchange="binance", market_type="futures", tick_process=False,
                         description="Counter asset — moves inversely to primary; short when primary is long"),
        ]

    async def execute(self, tick: TickData, asset_num: int) -> list[TradeSignal]:
        if asset_num != 0:
            return []

        lookback: int = self.params.get("lookback", 20)
        z_threshold: float = self.params.get("z_threshold", 2.0)
        amount: float = self.params.get("amount", 0.3)

        fetcher = InternalDataFetcher()
        btc_klines = await fetcher.get_klines("btcusdt", "1h", limit=lookback + 5)
        eth_klines = await fetcher.get_klines("ethusdt", "1h", limit=lookback + 5)

        if len(btc_klines) < lookback or len(eth_klines) < lookback:
            return []

        btc_closes = np.array([k.close for k in btc_klines[-lookback:]])
        eth_closes = np.array([k.close for k in eth_klines[-lookback:]])
        ratios = btc_closes / eth_closes

        mean = ratios.mean()
        std = ratios.std()
        if std == 0:
            return []

        current_ratio = tick.close / eth_closes[-1]
        z = (current_ratio - mean) / std

        if abs(z) < z_threshold:
            return []

        if z < -z_threshold:
            # BTC is cheap relative to ETH: long BTC, short ETH
            return [
                TradeSignal(execute=SignalSide.LONG, asset_num=0, exchange_num=0, market_type="futures", amount=amount, price=tick.close),
                TradeSignal(execute=SignalSide.SHORT, asset_num=1, exchange_num=0, market_type="futures", amount=amount),
            ]
        else:
            # BTC is expensive relative to ETH: short BTC, long ETH
            return [
                TradeSignal(execute=SignalSide.SHORT, asset_num=0, exchange_num=0, market_type="futures", amount=amount, price=tick.close),
                TradeSignal(execute=SignalSide.LONG, asset_num=1, exchange_num=0, market_type="futures", amount=amount),
            ]
