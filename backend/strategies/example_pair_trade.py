"""
Example multi-asset strategy: BTC/ETH pair trading (mean reversion on spread).

Legs required:
  leg_num=0  btcusdt  1h  futures  tick_process=True   role="primary"
  leg_num=1  ethusdt  1h  futures  tick_process=False  role="counter"

Signals:
  When the BTC/ETH ratio deviates > 2 std from rolling mean → enter pair trade:
    OPEN_LONG BTC (leg_num=0) + OPEN_SHORT ETH (leg_num=1) when ratio is low
    OPEN_SHORT BTC + OPEN_LONG ETH when ratio is high

Register:
    python tasks.py start-trader --strategy strategies.example_pair_trade.PairTradeStrategy
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from app.services.data_fetcher import Subscription
from app.services.strategy_context import StrategyContext
from app.services.strategy_executer import (
    AmountMode,
    ExecutionPlan,
    LegOrder,
    ParameterSchema,
    PriceMethod,
    SignalAction,
    StrategyExecuter,
)


class PairTradeStrategy(StrategyExecuter):
    """
    Mean-reversion pair trade on BTC/ETH price ratio.
    Enters when z-score of ratio exceeds threshold.
    Uses context.db for historical klines (leg_num=0 BTC, leg_num=1 ETH).
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
        if self.legs:
            return [
                Subscription(
                    symbol=l.symbol,
                    timeframe=l.timeframe,
                    exchange=l.exchange,
                    market_type=l.market_type,
                    tick_process=l.tick_process,
                )
                for l in self.legs
            ]
        return [
            Subscription(symbol="btcusdt", timeframe="1h", exchange="binance", market_type="futures", tick_process=True,
                         description="Primary — triggers execution; long when ratio is low"),
            Subscription(symbol="ethusdt", timeframe="1h", exchange="binance", market_type="futures", tick_process=False,
                         description="Counter — moves inversely to primary; short when primary is long"),
        ]

    async def execute(self, context: StrategyContext) -> Optional[ExecutionPlan]:
        if not context.tick.is_closed:
            return None
        # Only execute on the primary (leg_num=0) tick
        if context.leg_num != 0:
            return None

        tick = context.tick
        lookback: int = int(self.params.get("lookback", 20))
        z_threshold: float = float(self.params.get("z_threshold", 2.0))
        amount: float = float(self.params.get("amount", 0.3))

        btc_klines = await context.db.get_klines("btcusdt", "1h", limit=lookback + 5)
        eth_klines = await context.db.get_klines("ethusdt", "1h", limit=lookback + 5)

        if len(btc_klines) < lookback or len(eth_klines) < lookback:
            return None

        btc_closes = np.array([k.close for k in btc_klines[-lookback:]])
        eth_closes = np.array([k.close for k in eth_klines[-lookback:]])
        ratios = btc_closes / eth_closes

        mean = ratios.mean()
        std = ratios.std()
        if std == 0:
            return None

        current_ratio = tick.close / eth_closes[-1]
        z = (current_ratio - mean) / std

        if abs(z) < z_threshold:
            return None

        if z < -z_threshold:
            # BTC is cheap relative to ETH: long BTC, short ETH
            return ExecutionPlan(orders=[
                LegOrder(leg_num=0, action=SignalAction.OPEN_LONG, amount=amount,
                         amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED,
                         price_method=PriceMethod.MARKET, price=tick.close,
                         reason=f"z-score={z:.2f} < -{z_threshold}: BTC cheap vs ETH — long BTC"),
                LegOrder(leg_num=1, action=SignalAction.OPEN_SHORT, amount=amount,
                         amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED,
                         price_method=PriceMethod.MARKET,
                         reason=f"z-score={z:.2f} < -{z_threshold}: BTC cheap vs ETH — short ETH"),
            ])
        else:
            # BTC is expensive relative to ETH: short BTC, long ETH
            return ExecutionPlan(orders=[
                LegOrder(leg_num=0, action=SignalAction.OPEN_SHORT, amount=amount,
                         amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED,
                         price_method=PriceMethod.MARKET, price=tick.close,
                         reason=f"z-score={z:.2f} > +{z_threshold}: BTC expensive vs ETH — short BTC"),
                LegOrder(leg_num=1, action=SignalAction.OPEN_LONG, amount=amount,
                         amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED,
                         price_method=PriceMethod.MARKET,
                         reason=f"z-score={z:.2f} > +{z_threshold}: BTC expensive vs ETH — long ETH"),
            ])
