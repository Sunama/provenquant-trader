from __future__ import annotations

from datetime import datetime, timezone
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
            ParameterSchema(name="period", type="int", default=10, min=1, max=600, description="Period between side switch (seconds)"),
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
        period: int = int(self.params.get("period", 10))

        leg = context.get_leg(leg_num)
        fee_rate: float = leg.transaction_fee if leg else 0.0002

        history = await context.db.get_trade_history(
            context.config_id,
            symbol=tick.symbol,
            limit=1,
        )

        if not history:
            # No trades yet — open long to start
            return ExecutionPlan(orders=[
                LegOrder(
                    leg_num=leg_num,
                    action=SignalAction.OPEN_LONG,
                    amount=0.1,
                    amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED,
                    price_method=PriceMethod.MARKET,
                )
            ])

        last_trade = history[0]
        tick_dt = datetime.fromtimestamp(tick.time / 1000, tz=timezone.utc)
        elapsed_seconds = (tick_dt - last_trade.occurred_at).total_seconds()
        if elapsed_seconds < period:
            return None

        # Guard: only switch if unrealized PnL covers the round-trip fee cost (close + reopen)
        open_positions = await context.db.get_open_positions(context.config_id, symbol=tick.symbol)
        if open_positions:
            pos = open_positions[0]
            if pos.side == "long":
                unrealized_pnl = (tick.close - pos.entry_price) * pos.size
            else:
                unrealized_pnl = (pos.entry_price - tick.close) * pos.size
            switching_cost = pos.entry_price * pos.size * fee_rate * 2
            if unrealized_pnl <= switching_cost:
                return None

        # Switch side based on the last trade type
        if last_trade.trade_type in ("open_long", "close_short"):
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
                ),
            ])
        else:  # open_short or close_long
            return ExecutionPlan(orders=[
                LegOrder(
                    leg_num=leg_num,
                    action=SignalAction.CLOSE_SHORT,
                    amount=0.1,
                    amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED,
                    price_method=PriceMethod.MARKET,
                ),
                LegOrder(
                    leg_num=leg_num,
                    action=SignalAction.OPEN_LONG,
                    amount=0.1,
                    amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED,
                    price_method=PriceMethod.MARKET,
                ),
            ])
