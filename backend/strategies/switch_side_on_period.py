from __future__ import annotations

from typing import Optional

from app.services.data_fetcher import Subscription
from app.services.strategy_context import StrategyContext
from app.services.strategy_executer import (
    AmountMode,
    ExecutionPlan,
    IndicatorPoint,
    IndicatorSeries,
    LegOrder,
    ParameterSchema,
    PriceMethod,
    SignalAction,
    StrategyExecuter,
)


class SwitchSideOnPeriodStrategy(StrategyExecuter):

    @property
    def id(self) -> str:
        return "switch_side_on_period"

    @property
    def parameter_schema(self) -> list[ParameterSchema]:
        return [
            ParameterSchema(name="period", type="int", default=500, min=250, max=1000, description="Period between side switch"),
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
                    subscribe_depth=l.subscribe_depth,
                )
                for l in self.legs
            ]
        return [
            Subscription(symbol="btcusdt", timeframe="1m", exchange="binance", market_type="futures", tick_process=True)
        ]

    async def execute(self, context: StrategyContext) -> Optional[ExecutionPlan]:
        tick = context.tick
        leg_num = context.leg_num

        period: int = int(self.params.get("period", 500))
        
        status = await context.redis.get_status()
        
        if status is None or status == "neutral" or status == "short":
            await context.redis.set_status("long")
            
            # No status yet, open long
            return ExecutionPlan(orders=[
                LegOrder(
                    leg_num=leg_num,
                    action=SignalAction.OPEN_LONG,
                    amount=0.1,
                    amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED,
                    price_method=PriceMethod.MARKET,
                )
            ])
        elif status == "long":
            await context.redis.set_status("short")
            
            return ExecutionPlan(orders=[
                LegOrder(
                    leg_num=leg_num,
                    action=SignalAction.CLOSE_LONG,
                    amount=0.1,
                    amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED,
                    price_method=PriceMethod.MARKET,
                ),
                LegOrder(
                    leg_num=leg_num,
                    action=SignalAction.OPEN_SHORT,
                    amount=0.1,
                    amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED,
                    price_method=PriceMethod.MARKET,
                )
            ])

        return None
