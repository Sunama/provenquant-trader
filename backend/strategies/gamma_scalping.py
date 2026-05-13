"""
Gamma Scalping Strategy — Options-based volatility harvesting on BTC.

Mechanism:
  1. Enter an ATM Straddle (Long Call + Long Put) on Binance EAPI.
  2. Hedge delta exposure with BTC USDT-M futures so the portfolio stays
     delta-neutral at all times.
  3. On every 1m bar: recompute net delta (options Greeks + current futures
     hedge). If |net_delta| > threshold, rebalance the futures position.
  4. Exit when: profit target hit | stop loss | near expiry.

P&L formula:  Gamma profit (from BTC moves) − Theta decay (time cost)
Profitable when realized vol > implied vol priced into the options.

Design notes:
  - Options symbols are dynamic (e.g. "BTC-250515-95000-C"), so options
    positions are tracked entirely in Redis state rather than StrategyLegs.
  - The futures delta hedge uses the standard ExecutionPlan / LegOrder flow.
  - 1 Binance EAPI contract = 0.01 BTC (CONTRACT_SIZE).

Registration example (StrategyConfig):
  strategy_class = "strategies.gamma_scalping.GammaScalpingStrategy"
  assets = [
    { symbol: "btcusdt", exchange: "binance", timeframe: "1m",
      market_type: "futures", tick_process: true, role: "hedge" }
  ]
  params = {
    "expiry_target_days": 7,
    "delta_threshold": 0.002,
    "max_loss_pct": 0.50,
    "profit_target_pct": 0.30,
    "num_contracts": 1,
    "close_before_expiry_hours": 4.0,
  }
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from app.services.data_fetcher.binance_options import (
    CONTRACT_SIZE,
    BinanceOptionsDataFetcher,
)
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

# Redis state keys (all scoped via context.redis.set_state / get_state)
_K_STATUS = "straddle_status"        # "none" | "open"
_K_CALL   = "call_symbol"
_K_PUT    = "put_symbol"
_K_CALL_E = "call_entry_mark"        # USDT mark price at entry
_K_PUT_E  = "put_entry_mark"
_K_EXPIRY = "expiry_ms"              # Unix ms
_K_PREM   = "premium_paid_total"     # USDT (entry_call + entry_put) * n * unit
_K_NCON   = "num_contracts"
_K_HSIDE  = "hedge_side"             # "none" | "long" | "short"
_K_HSIZE  = "hedge_size"             # BTC (always positive)

_ALL_KEYS = [
    _K_STATUS, _K_CALL, _K_PUT, _K_CALL_E, _K_PUT_E,
    _K_EXPIRY, _K_PREM, _K_NCON, _K_HSIDE, _K_HSIZE,
]


class GammaScalpingStrategy(StrategyExecuter):
    """
    Options Gamma Scalping: ATM straddle on Binance EAPI + futures delta hedge.

    See module docstring for full design notes.
    """

    @property
    def id(self) -> str:
        return "gamma_scalping_btc_1m"

    @property
    def parameter_schema(self) -> list[ParameterSchema]:
        return [
            ParameterSchema(
                name="expiry_target_days", type="int", default=7, min=1, max=30,
                description="Target DTE when selecting the option expiry",
            ),
            ParameterSchema(
                name="delta_threshold", type="float", default=0.002, min=0.0001, max=0.1,
                description="Rebalance futures when |net_delta| (BTC) exceeds this value",
            ),
            ParameterSchema(
                name="max_loss_pct", type="float", default=0.50, min=0.05, max=0.99,
                description="Exit straddle if options P&L < −(this fraction) of premium paid",
            ),
            ParameterSchema(
                name="profit_target_pct", type="float", default=0.30, min=0.05, max=5.0,
                description="Take profit when options P&L ≥ (this fraction) of premium paid",
            ),
            ParameterSchema(
                name="num_contracts", type="int", default=1, min=1, max=100,
                description="Number of straddle contracts to open (1 contract = 0.01 BTC)",
            ),
            ParameterSchema(
                name="close_before_expiry_hours", type="float", default=4.0, min=0.5, max=48.0,
                description="Force-exit the straddle this many hours before option expiry",
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

        expiry_target_days: int = int(self.params.get("expiry_target_days", 7))
        delta_threshold: float = float(self.params.get("delta_threshold", 0.002))
        max_loss_pct: float = float(self.params.get("max_loss_pct", 0.50))
        profit_target_pct: float = float(self.params.get("profit_target_pct", 0.30))
        num_contracts: int = int(self.params.get("num_contracts", 1))
        close_before_expiry_hours: float = float(self.params.get("close_before_expiry_hours", 4.0))

        straddle_status = await context.redis.get_state(_K_STATUS, "none")

        if straddle_status == "none":
            return await self._enter_straddle(
                context, tick, leg_num,
                expiry_target_days, num_contracts,
            )

        if straddle_status == "open":
            return await self._manage_straddle(
                context, tick, leg_num,
                delta_threshold, max_loss_pct, profit_target_pct,
                num_contracts, close_before_expiry_hours,
            )

        return None

    # ── Straddle entry ────────────────────────────────────────────────────────

    async def _enter_straddle(
        self,
        context: StrategyContext,
        tick,
        leg_num: int,
        expiry_target_days: int,
        num_contracts: int,
    ) -> Optional[ExecutionPlan]:
        try:
            spot_price = tick.close
            call_info, put_info = await BinanceOptionsDataFetcher.fetch_option_chain(
                spot_price=spot_price, target_dte=expiry_target_days,
            )
            if call_info is None or put_info is None:
                logger.warning("[GammaScalping] No ATM straddle available — waiting")
                return None

            import asyncio as _asyncio
            call_mark, put_mark = await _asyncio.gather(
                BinanceOptionsDataFetcher.fetch_option_mark_rest(call_info.symbol),
                BinanceOptionsDataFetcher.fetch_option_mark_rest(put_info.symbol),
            )
            if call_mark is None or put_mark is None:
                logger.warning("[GammaScalping] Could not fetch entry mark prices — skipping")
                return None

            # Total premium paid in USDT = (call + put) per contract * n contracts
            premium_paid = (call_mark.mark_price + put_mark.mark_price) * num_contracts * CONTRACT_SIZE

            await context.redis.set_state(_K_STATUS, "open")
            await context.redis.set_state(_K_CALL,   call_info.symbol)
            await context.redis.set_state(_K_PUT,    put_info.symbol)
            await context.redis.set_state(_K_CALL_E, str(call_mark.mark_price))
            await context.redis.set_state(_K_PUT_E,  str(put_mark.mark_price))
            await context.redis.set_state(_K_EXPIRY, str(call_info.expiry_ms))
            await context.redis.set_state(_K_PREM,   str(premium_paid))
            await context.redis.set_state(_K_NCON,   str(num_contracts))
            await context.redis.set_state(_K_HSIDE,  "none")
            await context.redis.set_state(_K_HSIZE,  "0.0")

            logger.info(
                f"[GammaScalping] ENTERED straddle | strike={call_info.strike} "
                f"dte={call_info.dte:.1f}d | "
                f"call={call_info.symbol} mark={call_mark.mark_price:.2f} Δ={call_mark.delta:+.4f} | "
                f"put={put_info.symbol}  mark={put_mark.mark_price:.2f} Δ={put_mark.delta:+.4f} | "
                f"premium_usdt={premium_paid:.2f} spot={spot_price:.2f}"
            )
            # No futures order on entry — ATM straddle starts nearly delta-neutral
            return None

        except Exception:
            logger.exception("[GammaScalping] Error entering straddle")
            return None

    # ── Straddle management (called on every 1m bar while open) ──────────────

    async def _manage_straddle(
        self,
        context: StrategyContext,
        tick,
        leg_num: int,
        delta_threshold: float,
        max_loss_pct: float,
        profit_target_pct: float,
        num_contracts: int,
        close_before_expiry_hours: float,
    ) -> Optional[ExecutionPlan]:
        try:
            # Load state
            call_symbol  = await context.redis.get_state(_K_CALL)
            put_symbol   = await context.redis.get_state(_K_PUT)
            call_entry   = float(await context.redis.get_state(_K_CALL_E, "0"))
            put_entry    = float(await context.redis.get_state(_K_PUT_E,  "0"))
            expiry_ms    = int(  await context.redis.get_state(_K_EXPIRY, "0"))
            premium_paid = float(await context.redis.get_state(_K_PREM,   "0"))
            n_contracts  = int(  await context.redis.get_state(_K_NCON, str(num_contracts)))
            hedge_side   =       await context.redis.get_state(_K_HSIDE, "none")
            hedge_size   = float(await context.redis.get_state(_K_HSIZE, "0.0"))

            if not call_symbol or not put_symbol:
                await self._clear_straddle_state(context)
                return None

            # Prefer Redis (WebSocket feed) if available; fall back to REST
            import asyncio as _asyncio
            call_mark_raw, put_mark_raw = await _asyncio.gather(
                context.redis.get_option_mark(call_symbol),
                context.redis.get_option_mark(put_symbol),
            )

            if call_mark_raw is None or put_mark_raw is None:
                # WebSocket not yet feeding these symbols — use REST
                call_mark_rest, put_mark_rest = await _asyncio.gather(
                    BinanceOptionsDataFetcher.fetch_option_mark_rest(call_symbol),
                    BinanceOptionsDataFetcher.fetch_option_mark_rest(put_symbol),
                )
                if call_mark_rest is None or put_mark_rest is None:
                    logger.warning("[GammaScalping] Could not fetch current marks — skipping tick")
                    return None
                call_mp = call_mark_rest.mark_price
                call_delta = call_mark_rest.delta
                call_gamma = call_mark_rest.gamma
                put_mp = put_mark_rest.mark_price
                put_delta = put_mark_rest.delta
            else:
                call_mp    = float(call_mark_raw["mark_price"])
                call_delta = float(call_mark_raw["delta"])
                call_gamma = float(call_mark_raw["gamma"])
                put_mp     = float(put_mark_raw["mark_price"])
                put_delta  = float(put_mark_raw["delta"])

            # ── P&L ──────────────────────────────────────────────────────────
            entry_value   = (call_entry + put_entry) * n_contracts * CONTRACT_SIZE
            current_value = (call_mp    + put_mp)    * n_contracts * CONTRACT_SIZE
            pnl           = current_value - entry_value
            pnl_pct       = pnl / entry_value if entry_value > 0 else 0.0

            # ── Time to expiry ────────────────────────────────────────────────
            now_ms           = int(datetime.now(timezone.utc).timestamp() * 1000)
            hours_to_expiry  = (expiry_ms - now_ms) / (1000 * 3600)

            # ── Net delta (BTC) ───────────────────────────────────────────────
            # options_delta_btc = Greek delta × contracts × contract_size
            options_delta_btc = (call_delta + put_delta) * n_contracts * CONTRACT_SIZE
            # futures hedge contribution: long = +BTC, short = -BTC
            futures_delta_btc = (
                +hedge_size if hedge_side == "long"
                else -hedge_size if hedge_side == "short"
                else 0.0
            )
            net_delta_btc = options_delta_btc + futures_delta_btc

            logger.debug(
                f"[GammaScalping] tick={tick.close:.2f} "
                f"pnl={pnl:+.2f} USDT ({pnl_pct:+.1%}) | "
                f"Δcall={call_delta:+.4f} Δput={put_delta:+.4f} "
                f"Γcall={call_gamma:.6f} | "
                f"net_delta={net_delta_btc:+.5f} BTC | "
                f"tte={hours_to_expiry:.1f}h"
            )

            # ── Exit conditions (checked in priority order) ───────────────────
            if pnl_pct >= profit_target_pct:
                return await self._exit_straddle(
                    context, tick, leg_num, hedge_side, hedge_size, pnl,
                    reason=f"profit_target pnl={pnl_pct:+.1%}",
                )
            if pnl_pct <= -max_loss_pct:
                return await self._exit_straddle(
                    context, tick, leg_num, hedge_side, hedge_size, pnl,
                    reason=f"stop_loss pnl={pnl_pct:+.1%}",
                )
            if hours_to_expiry < close_before_expiry_hours:
                return await self._exit_straddle(
                    context, tick, leg_num, hedge_side, hedge_size, pnl,
                    reason=f"near_expiry tte={hours_to_expiry:.1f}h",
                )

            # ── Delta rebalance ───────────────────────────────────────────────
            if abs(net_delta_btc) > delta_threshold:
                return await self._rebalance_hedge(
                    context, tick, leg_num, net_delta_btc, hedge_side, hedge_size,
                )

            return None

        except Exception:
            logger.exception("[GammaScalping] Error managing straddle")
            return None

    # ── Delta hedge rebalance ─────────────────────────────────────────────────

    async def _rebalance_hedge(
        self,
        context: StrategyContext,
        tick,
        leg_num: int,
        net_delta_btc: float,
        current_hedge_side: str,
        current_hedge_size: float,
    ) -> Optional[ExecutionPlan]:
        orders: list[LegOrder] = []

        # 1. Close existing futures hedge (full position)
        if current_hedge_side == "long" and current_hedge_size > 0:
            orders.append(LegOrder(
                leg_num=leg_num,
                action=SignalAction.CLOSE_LONG,
                amount=1.0,
                amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED,
                price_method=PriceMethod.MARKET,
                price=tick.close,
            ))
        elif current_hedge_side == "short" and current_hedge_size > 0:
            orders.append(LegOrder(
                leg_num=leg_num,
                action=SignalAction.CLOSE_SHORT,
                amount=1.0,
                amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED,
                price_method=PriceMethod.MARKET,
                price=tick.close,
            ))

        # 2. Open new hedge to neutralise net_delta
        #    net_delta > 0  → straddle is net long BTC  → SHORT futures
        #    net_delta < 0  → straddle is net short BTC → LONG futures
        target_size = abs(net_delta_btc)
        if net_delta_btc > 0:
            new_side = "short"
            action   = SignalAction.OPEN_SHORT
        else:
            new_side = "long"
            action   = SignalAction.OPEN_LONG

        orders.append(LegOrder(
            leg_num=leg_num,
            action=action,
            amount=target_size,
            amount_mode=AmountMode.UNITS,
            price_method=PriceMethod.MARKET,
            price=tick.close,
        ))

        await context.redis.set_state(_K_HSIDE, new_side)
        await context.redis.set_state(_K_HSIZE, str(target_size))

        logger.info(
            f"[GammaScalping] HEDGE REBALANCE | "
            f"net_delta={net_delta_btc:+.5f} BTC → {action.value} {target_size:.5f} BTC "
            f"@ {tick.close:.2f}"
        )
        return ExecutionPlan(orders=orders)

    # ── Exit straddle ─────────────────────────────────────────────────────────

    async def _exit_straddle(
        self,
        context: StrategyContext,
        tick,
        leg_num: int,
        hedge_side: str,
        hedge_size: float,
        pnl: float,
        reason: str,
    ) -> Optional[ExecutionPlan]:
        orders: list[LegOrder] = []

        # Close futures hedge if one is open
        if hedge_side == "long" and hedge_size > 0:
            orders.append(LegOrder(
                leg_num=leg_num,
                action=SignalAction.CLOSE_LONG,
                amount=1.0,
                amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED,
                price_method=PriceMethod.MARKET,
                price=tick.close,
            ))
        elif hedge_side == "short" and hedge_size > 0:
            orders.append(LegOrder(
                leg_num=leg_num,
                action=SignalAction.CLOSE_SHORT,
                amount=1.0,
                amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED,
                price_method=PriceMethod.MARKET,
                price=tick.close,
            ))

        await self._clear_straddle_state(context)

        logger.info(
            f"[GammaScalping] EXIT straddle | reason={reason} | "
            f"options_pnl={pnl:+.2f} USDT"
        )
        return ExecutionPlan(orders=orders) if orders else None

    # ── State helpers ─────────────────────────────────────────────────────────

    async def _clear_straddle_state(self, context: StrategyContext) -> None:
        for key in _ALL_KEYS:
            await context.redis.set_state(key, "")
        # Explicitly mark as "none" so next tick re-enters
        await context.redis.set_state(_K_STATUS, "none")
