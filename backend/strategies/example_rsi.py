"""
Example strategy: simple RSI mean-reversion (futures, status-aware).

Register via StrategyConfig with:
  strategy_class = "strategies.example_rsi.RSIStrategy"
  assets = [{ symbol: "btcusdt", exchange: "binance", timeframe: "30m", market_type: "futures", tick_process: true }]
  params = { "period": 14, "oversold": 30, "overbought": 70, "amount": 0.5 }
"""
from __future__ import annotations

from app.services.data_fetcher import Subscription, TickData
from app.services.strategy_executer import (
    ParameterSchema,
    PriceMethod,
    SignalAction,
    StrategyAssetConfig,
    StrategyExecuter,
    TradeSignal,
)


def _rsi(closes: list[float], period: int = 14) -> float:
    import numpy as np
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
    Go long when RSI < oversold threshold, short when RSI > overbought threshold.

    Uses StrategyStatus to avoid re-entering the same position direction and to
    emit explicit OPEN/CLOSE signals for futures trading.

    Status values: "neutral" | "long" | "short"
    """

    @property
    def id(self) -> str:
        return "rsi_btcusdt_30m"

    @property
    def parameter_schema(self) -> list[ParameterSchema]:
        return [
            ParameterSchema(name="period", type="int", default=14, min=2, max=100, description="RSI lookback period"),
            ParameterSchema(name="oversold", type="float", default=30.0, min=10.0, max=50.0, description="RSI oversold threshold → OPEN LONG signal"),
            ParameterSchema(name="overbought", type="float", default=70.0, min=50.0, max=90.0, description="RSI overbought threshold → OPEN SHORT signal"),
            ParameterSchema(name="amount", type="float", default=0.5, min=0.01, max=1.0, description="Fraction of available balance to use"),
            ParameterSchema(name="tp_pct", type="float", default=0.02, min=0.001, max=0.5, description="Take-profit %"),
            ParameterSchema(name="sl_pct", type="float", default=0.01, min=0.001, max=0.5, description="Stop-loss %"),
        ]

    @property
    def subscriptions(self) -> list[Subscription]:
        if self.assets:
            return [
                Subscription(
                    symbol=a.symbol,
                    timeframe=a.timeframe,
                    exchange=a.exchange,
                    market_type=a.market_type,
                    tick_process=a.tick_process,
                )
                for a in self.assets
            ]
        return [
            Subscription(symbol="btcusdt", timeframe="30m", exchange="binance", market_type="futures", tick_process=True)
        ]

    async def execute(self, tick: TickData, asset_num: int = 0) -> list[TradeSignal]:
        period: int = int(self.params.get("period", 14))
        oversold: float = float(self.params.get("oversold", 30.0))
        overbought: float = float(self.params.get("overbought", 70.0))
        amount: float = float(self.params.get("amount", 0.5))
        tp_pct: float = float(self.params.get("tp_pct", 0.02))
        sl_pct: float = float(self.params.get("sl_pct", 0.01))

        # Fetch recent closes from Redis (survives across ephemeral Celery task instances)
        closes = await self.get_recent_closes(tick.symbol, tick.timeframe, period + 10)
        rsi = _rsi(closes, period)

        status = await self.get_status()

        if rsi < oversold and status != "long":
            signals: list[TradeSignal] = []
            # Close short position first if currently short
            if status == "short":
                signals.append(TradeSignal(
                    execute=SignalAction.CLOSE_SHORT,
                    asset_num=asset_num,
                    exchange_num=0,
                    market_type="futures",
                    amount=1.0,
                    price_method=PriceMethod.MARKET,
                    price=tick.close,
                ))
            # Open long
            signals.append(TradeSignal(
                execute=SignalAction.OPEN_LONG,
                asset_num=asset_num,
                exchange_num=0,
                market_type="futures",
                amount=amount,
                price_method=PriceMethod.MARKET,
                price=tick.close,
                tp_pct=tp_pct,
                sl_pct=sl_pct,
            ))
            await self.set_status("long")
            return signals

        if rsi > overbought and status != "short":
            signals = []
            # Close long position first if currently long
            if status == "long":
                signals.append(TradeSignal(
                    execute=SignalAction.CLOSE_LONG,
                    asset_num=asset_num,
                    exchange_num=0,
                    market_type="futures",
                    amount=1.0,
                    price_method=PriceMethod.MARKET,
                    price=tick.close,
                ))
            # Open short
            signals.append(TradeSignal(
                execute=SignalAction.OPEN_SHORT,
                asset_num=asset_num,
                exchange_num=0,
                market_type="futures",
                amount=amount,
                price_method=PriceMethod.MARKET,
                price=tick.close,
                tp_pct=tp_pct,
                sl_pct=sl_pct,
            ))
            await self.set_status("short")
            return signals

        return []

    def indicators(self, klines: list):
        from app.services.strategy_executer import IndicatorSeries, IndicatorPoint
        period = int(self.params.get("period", 14))
        closes = [k.close for k in klines]
        points = [
            IndicatorPoint(
                time=int(klines[i].time.timestamp() * 1000),
                value=_rsi(closes[:i + 1], period),
            )
            for i in range(len(closes))
        ]
        return [IndicatorSeries(name=f"RSI({period})", plot="oscillator", color="#9c27b0", data=points)]
