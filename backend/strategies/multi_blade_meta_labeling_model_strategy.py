"""
Multi Blade Meta Labeling Model Strategy — Triple Barrier with multi-model meta labels.

Fetches ML predictions from ProvenQuant API and opens futures positions based on:
  1. CUSUM filter triggered
  2. Meta model probability > threshold (from model params)
  3. Model Sharpe ratio >= user-defined minimum

Signals originate from dollar bars constructed on 1m data, so they appear
approximately every 30 minutes on average. This strategy subscribes to 1m
bars to catch each new signal within its 1–2 minute validity window.

Exit: closes the position when the prediction's t1 barrier time expires.

Registration example (StrategyConfig):
  strategy_class = "strategies.multi_blade_meta_labeling_model_strategy.MultiBladeMetaLabelingModelStrategy"
  assets = [
    { symbol: "btcusdt", exchange: "binance", timeframe: "1m",
      market_type: "futures", tick_process: true, role: "primary" }
  ]
  params = {
    "enable_long": true,
    "enable_short": true,
    "min_sharpe_ratio": 1.0,
    "amount": 0.5,
  }
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

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

logger = logging.getLogger(__name__)

# Redis state keys (all scoped via config_id by RedisDataFetcher)
_K_STATUS    = "mb_status"      # "neutral" | "long" | "short"
_K_T1_MS     = "mb_t1_ms"       # Unix ms when the position must be closed
_K_SIGNAL_MS = "mb_signal_ms"   # Unix ms of the prediction we entered on
_K_TP_PCT    = "mb_tp_pct"      # tp_pct stored when opening (for TP/SL check)
_K_SL_PCT    = "mb_sl_pct"      # sl_pct stored when opening (for TP/SL check)

# A prediction is considered "fresh" if the current time is within this window
# of its bar time (signals come from 1m bars, ~1–2 bar lag is normal)
_MAX_SIGNAL_AGE_MS = 60 * 60 * 1000  # 1 hour

_PQ_URL = "https://www.provenquant.com/api/assets/{symbol}/ml-predictions?timeframe=30m&days_back=7"

# Matches keys like "long_meta_model_2_1_prob_1" or "short_meta_model_2.5_1.0_prob_1"
_META_KEY_RE = re.compile(
    r"^(long|short)_meta_model_([\d.]+)_([\d.]+)_prob_1$"
)


def _to_ms(t: Any) -> int:
    """Normalise a timestamp to Unix milliseconds."""
    if isinstance(t, str):
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
            return int(dt.timestamp() * 1000)
        except ValueError:
            pass
    v = int(float(t))
    return v * 1000 if v < 1_000_000_000_000 else v


def _as_bool(val: Any, default: bool) -> bool:
    if val is None:
        return default
    if isinstance(val, str):
        return val.lower() not in ("false", "0", "no", "")
    return bool(val)


class MultiBladeMetaLabelingModelStrategy(StrategyExecuter):
    """
    Opens long/short futures positions using Triple Barrier meta-model signals
    from the ProvenQuant ML predictions API.
    """

    @property
    def id(self) -> str:
        return "multi_blade_meta_labeling_model"

    @property
    def parameter_schema(self) -> list[ParameterSchema]:
        return [
            ParameterSchema(
                name="enable_long", type="bool", default=True,
                description="Allow opening long positions",
            ),
            ParameterSchema(
                name="enable_short", type="bool", default=True,
                description="Allow opening short positions",
            ),
            ParameterSchema(
                name="min_sharpe_ratio", type="float", default=1.0, min=0.0, max=4.0,
                description="Minimum Sharpe ratio a meta model must have to be traded",
            ),
            ParameterSchema(
                name="amount", type="float", default=0.5, min=0.01, max=1.0,
                description="Fraction of available balance to allocate per trade",
            ),
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
            Subscription(
                symbol="btcusdt", timeframe="1m",
                exchange="binance", market_type="futures",
                tick_process=True,
            )
        ]

    # ── Main entry point ──────────────────────────────────────────────────────

    async def execute(self, context: StrategyContext) -> Optional[ExecutionPlan]:
        tick = context.tick
        leg_num = context.leg_num

        enable_long = _as_bool(self.params.get("enable_long"), True)
        enable_short = _as_bool(self.params.get("enable_short"), True)
        min_sharpe = float(self.params.get("min_sharpe_ratio", 1.0))
        amount = float(self.params.get("amount", 0.5))

        status = await context.redis.get_state(_K_STATUS, "neutral")
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        # ── Manage open position ──────────────────────────────────────────────
        if status in ("long", "short"):
            # TP/SL check (takes priority over t1 expiry)
            tp_pct_stored = float(await context.redis.get_state(_K_TP_PCT, "0"))
            sl_pct_stored = float(await context.redis.get_state(_K_SL_PCT, "0"))
            if tp_pct_stored > 0 and sl_pct_stored > 0:
                open_positions = await context.db.get_open_positions(context.config_id, symbol=tick.symbol)
                if open_positions:
                    pos = open_positions[0]
                    if status == "long":
                        tp_hit = tick.close >= pos.entry_price * (1 + tp_pct_stored)
                        sl_hit = tick.close <= pos.entry_price * (1 - sl_pct_stored)
                    else:
                        tp_hit = tick.close <= pos.entry_price * (1 - tp_pct_stored)
                        sl_hit = tick.close >= pos.entry_price * (1 + sl_pct_stored)
                    if tp_hit or sl_hit:
                        hit_label = "Take-profit" if tp_hit else "Stop-loss"
                        return await self._close_position_tp_sl(
                            context, tick, leg_num, status,
                            reason=f"{hit_label} hit at {tick.close:.2f}",
                        )

            # t1 barrier expiry
            t1_ms = int(await context.redis.get_state(_K_T1_MS, "0"))
            if t1_ms > 0 and now_ms >= t1_ms:
                return await self._close_position(context, tick, leg_num, status)
            return None

        # ── Evaluate new signal (closed bars only — avoids per-tick API calls) ─
        if not tick.is_closed:
            return None

        data = await self._fetch_predictions(tick.symbol)
        if not data:
            return None

        model = data.get("model", {})
        predictions: list[dict] = data.get("predictions", [])
        if not predictions:
            return None

        prediction = self._latest_fresh_prediction(predictions, now_ms)
        if prediction is None:
            return None

        values: dict = prediction.get("values", {})
        t1_raw = values.get("t1")
        if not t1_raw:
            return None

        #if not _as_bool(values.get("is_cusum_triggered"), False):
        #    return None

        volatility = float(values.get("volatility", 0))
        if volatility <= 0:
            return None

        signal = self._best_signal(
            values, model, enable_long, enable_short, min_sharpe, volatility
        )
        if signal is None:
            return None

        side, tp_pct, sl_pct, open_reason = signal
        t1_ms = _to_ms(t1_raw)
        signal_ms = _to_ms(prediction["time"])
        action = SignalAction.OPEN_LONG if side == "long" else SignalAction.OPEN_SHORT

        await context.redis.set_state(_K_STATUS, side)
        await context.redis.set_state(_K_T1_MS, str(t1_ms))
        await context.redis.set_state(_K_SIGNAL_MS, str(signal_ms))
        await context.redis.set_state(_K_TP_PCT, str(tp_pct))
        await context.redis.set_state(_K_SL_PCT, str(sl_pct))

        t1_iso = datetime.fromtimestamp(t1_ms / 1000, tz=timezone.utc).isoformat()
        logger.info(
            f"[MBMLM] OPEN {side.upper()} | symbol={tick.symbol} "
            f"tp={tp_pct:.4f} sl={sl_pct:.4f} t1={t1_iso}"
        )

        return ExecutionPlan(orders=[
            LegOrder(
                leg_num=leg_num,
                action=action,
                amount=amount,
                amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED,
                price_method=PriceMethod.MARKET,
                price=tick.close,
                tp_pct=tp_pct,
                sl_pct=sl_pct,
                reason=open_reason,
            )
        ])

    # ── Signal evaluation helpers ─────────────────────────────────────────────

    def _latest_fresh_prediction(
        self, predictions: list[dict], now_ms: int
    ) -> Optional[dict]:
        """Return the most recent prediction still within _MAX_SIGNAL_AGE_MS."""
        sorted_preds = sorted(
            predictions,
            key=lambda p: _to_ms(p.get("time", 0)),
            reverse=True,
        )
        for pred in sorted_preds:
            age_ms = now_ms - _to_ms(pred.get("time", 0))
            if 0 <= age_ms <= _MAX_SIGNAL_AGE_MS:
                return pred
        return None

    def _best_signal(
        self,
        values: dict,
        model: dict,
        enable_long: bool,
        enable_short: bool,
        min_sharpe: float,
        volatility: float,
    ) -> Optional[tuple[str, float, float, str]]:
        """
        Scan all meta model probability keys in `values` and return
        (side, tp_pct, sl_pct, reason) for the highest-probability qualifying signal,
        or None if nothing passes the filters.
        """
        model_params = model.get("params", {})
        model_results = model.get("result", {})

        best_prob = -1.0
        best: Optional[tuple[str, float, float, str]] = None

        for key, prob_raw in values.items():
            match = _META_KEY_RE.match(key)
            if not match:
                continue

            side = match.group(1)
            tp_str = match.group(2)
            sl_str = match.group(3)
            model_key = f"{side}_meta_model_{tp_str}_{sl_str}"

            if side == "long" and not enable_long:
                continue
            if side == "short" and not enable_short:
                continue

            try:
                threshold = float(
                    model_params[side]["meta_models"][model_key]["threshold"]
                )
                sharpe = float(
                    model_results[side]["meta_models"][model_key]
                    ["backtest_metrics"]["sharpe_ratio"]
                )
                prob = float(prob_raw)
            except (KeyError, TypeError, ValueError):
                logger.debug(f"[MBMLM] Missing metadata for {model_key} — skipping")
                continue

            if prob <= threshold:
                continue
            if sharpe < min_sharpe:
                continue

            if prob > best_prob:
                best_prob = prob
                reason_str = f"MBMLM {side}: prob={prob:.3f} sharpe={sharpe:.2f} model={model_key}"
                best = (side, float(tp_str) * volatility, float(sl_str) * volatility, reason_str)

        return best

    # ── Position close ────────────────────────────────────────────────────────

    async def _close_position(
        self,
        context: StrategyContext,
        tick,
        leg_num: int,
        status: str,
    ) -> ExecutionPlan:
        action = SignalAction.CLOSE_LONG if status == "long" else SignalAction.CLOSE_SHORT

        await context.redis.set_state(_K_STATUS, "neutral")
        await context.redis.set_state(_K_T1_MS, "0")
        await context.redis.set_state(_K_SIGNAL_MS, "0")
        await context.redis.set_state(_K_TP_PCT, "0")
        await context.redis.set_state(_K_SL_PCT, "0")

        logger.info(
            f"[MBMLM] CLOSE {status.upper()} | t1_expired | price={tick.close}"
        )
        return ExecutionPlan(orders=[
            LegOrder(
                leg_num=leg_num,
                action=action,
                amount=1.0,
                amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED,
                price_method=PriceMethod.MARKET,
                price=tick.close,
                reason=f"t1_barrier_expired (was {status})",
            )
        ])

    async def _close_position_tp_sl(
        self,
        context: StrategyContext,
        tick,
        leg_num: int,
        status: str,
        reason: str,
    ) -> ExecutionPlan:
        action = SignalAction.CLOSE_LONG if status == "long" else SignalAction.CLOSE_SHORT

        await context.redis.set_state(_K_STATUS, "neutral")
        await context.redis.set_state(_K_T1_MS, "0")
        await context.redis.set_state(_K_SIGNAL_MS, "0")
        await context.redis.set_state(_K_TP_PCT, "0")
        await context.redis.set_state(_K_SL_PCT, "0")

        logger.info(f"[MBMLM] CLOSE {status.upper()} | {reason} | price={tick.close}")
        return ExecutionPlan(orders=[
            LegOrder(
                leg_num=leg_num,
                action=action,
                amount=1.0,
                amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED,
                price_method=PriceMethod.MARKET,
                price=tick.close,
                reason=reason,
            )
        ])

    # ── API fetch ─────────────────────────────────────────────────────────────

    async def _fetch_predictions(self, symbol: str) -> Optional[dict]:
        """Fetch ML predictions from the ProvenQuant REST API."""
        url = _PQ_URL.format(symbol=symbol)
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning(
                    f"[MBMLM] API {resp.status_code} for symbol={symbol}"
                )
                return None
            return resp.json()
        except Exception:
            logger.exception(f"[MBMLM] Failed to fetch predictions for {symbol}")
            return None
