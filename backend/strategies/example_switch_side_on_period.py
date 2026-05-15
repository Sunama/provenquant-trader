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
            ParameterSchema(name="tp_pct", type="float", default=0.02, min=0.001, max=0.5, description="Take profit percentage (e.g. 0.02 for 2%)"),
            ParameterSchema(name="sl_pct", type="float", default=0.01, min=0.001, max=0.5, description="Stop loss percentage (e.g. 0.01 for 1%)"),
        ]

    @property
    def subscriptions(self) -> list[Subscription]:
        _desc = "Primary OHLCV bar feed — switches between long and short on a fixed time period"
        if self.legs:
            return [
                Subscription(
                    symbol=self.legs[0].symbol,
                    timeframe=self.legs[0].timeframe,
                    exchange=self.legs[0].exchange,
                    market_type=self.legs[0].market_type,
                    tick_process=True,
                    subscribe_depth=False,
                    description=_desc,
                )
            ]
        return [
            Subscription(symbol="btcusdt", timeframe="1m", exchange="binance",
                         market_type="futures", tick_process=True, description=_desc)
        ]

    async def execute(self, context: StrategyContext) -> Optional[ExecutionPlan]:
        tick = context.tick
        leg_num = context.leg_num
        period: int = int(self.params.get("period", 10))
        tp_pct: float = float(self.params.get("tp_pct", 0.02))
        sl_pct: float = float(self.params.get("sl_pct", 0.01))

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
                    amount=0.9,
                    amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED,
                    price_method=PriceMethod.MARKET,
                    tp_pct=tp_pct,
                    sl_pct=sl_pct,
                    reason="Initial entry — no prior trades",
                    leverage=self.legs[leg_num].leverage,
                )
            ])

        open_positions = await context.db.get_open_positions(context.config_id, symbol=tick.symbol)

        # ── TP / SL check (highest priority) ──────────────────────────
        if open_positions:
            pos = open_positions[0]
            if pos.side == "long":
                tp_hit = tick.close >= pos.entry_price * (1 + tp_pct)
                sl_hit = tick.close <= pos.entry_price * (1 - sl_pct)
            else:
                tp_hit = tick.close <= pos.entry_price * (1 - tp_pct)
                sl_hit = tick.close >= pos.entry_price * (1 + sl_pct)

            if tp_hit or sl_hit:
                hit_label = "Take-profit" if tp_hit else "Stop-loss"
                flip_label = "TP" if tp_hit else "SL"
                if pos.side == "long":
                    return ExecutionPlan(orders=[
                        LegOrder(
                            leg_num=leg_num,
                            action=SignalAction.CLOSE_LONG,
                            amount=0.9,
                            amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED,
                            price_method=PriceMethod.MARKET,
                            reason=f"{hit_label} hit at {tick.close:.2f}",
                        ),
                        LegOrder(
                            leg_num=leg_num,
                            action=SignalAction.OPEN_SHORT,
                            amount=0.9,
                            amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED,
                            price_method=PriceMethod.MARKET,
                            tp_pct=tp_pct,
                            sl_pct=sl_pct,
                            reason=f"Flipping long→short after {flip_label}",
                            leverage=self.legs[leg_num].leverage,
                        ),
                    ])
                else:
                    return ExecutionPlan(orders=[
                        LegOrder(
                            leg_num=leg_num,
                            action=SignalAction.CLOSE_SHORT,
                            amount=0.9,
                            amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED,
                            price_method=PriceMethod.MARKET,
                            reason=f"{hit_label} hit at {tick.close:.2f}",
                        ),
                        LegOrder(
                            leg_num=leg_num,
                            action=SignalAction.OPEN_LONG,
                            amount=0.9,
                            amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED,
                            price_method=PriceMethod.MARKET,
                            tp_pct=tp_pct,
                            sl_pct=sl_pct,
                            reason=f"Flipping short→long after {flip_label}",
                            leverage=self.legs[leg_num].leverage,
                        ),
                    ])

        # ── Period-based side switch ───────────────────────────────────
        last_trade = history[0]
        tick_dt = datetime.fromtimestamp(tick.time / 1000, tz=timezone.utc)
        elapsed_seconds = (tick_dt - last_trade.occurred_at).total_seconds()
        if elapsed_seconds < period:
            return None

        # Guard: only switch if unrealized PnL covers the round-trip fee cost (close + reopen)
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
                    amount=0.9,
                    amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED,
                    price_method=PriceMethod.MARKET,
                    reason=f"Period {elapsed_seconds:.0f}s/{period}s elapsed — switching side",
                ),
                LegOrder(
                    leg_num=leg_num,
                    action=SignalAction.OPEN_SHORT,
                    amount=0.9,
                    amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED,
                    price_method=PriceMethod.MARKET,
                    tp_pct=tp_pct,
                    sl_pct=sl_pct,
                    reason=f"Period switch: opening short after {elapsed_seconds:.0f}s",
                    leverage=self.legs[leg_num].leverage,
                ),
            ])
        else:  # open_short or close_long
            return ExecutionPlan(orders=[
                LegOrder(
                    leg_num=leg_num,
                    action=SignalAction.CLOSE_SHORT,
                    amount=0.9,
                    amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED,
                    price_method=PriceMethod.MARKET,
                    reason=f"Period {elapsed_seconds:.0f}s/{period}s elapsed — switching side",
                ),
                LegOrder(
                    leg_num=leg_num,
                    action=SignalAction.OPEN_LONG,
                    amount=0.9,
                    amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED,
                    price_method=PriceMethod.MARKET,
                    tp_pct=tp_pct,
                    sl_pct=sl_pct,
                    reason=f"Period switch: opening long after {elapsed_seconds:.0f}s",
                    leverage=self.legs[leg_num].leverage,
                ),
            ])
