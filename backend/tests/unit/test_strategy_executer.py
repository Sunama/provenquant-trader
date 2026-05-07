"""
Unit tests for the StrategyExecuter base class and related dataclasses.
No external services required.
"""
import pytest
from app.services.strategy_executer import (
    ParameterSchema,
    SignalSide,
    StrategyAssetConfig,
    StrategyExecuter,
    TradeSignal,
)
from app.services.data_fetcher import Subscription, TickData


# ── Minimal concrete implementations for testing ──────────────────────

class _ModernStrategy(StrategyExecuter):
    """New-style strategy: execute(tick, asset_num) -> list[TradeSignal]."""

    @property
    def id(self) -> str:
        return "modern_test"

    @property
    def parameter_schema(self):
        return []

    @property
    def subscriptions(self):
        return [Subscription("btcusdt", "1m")]

    async def execute(self, tick: TickData, asset_num: int) -> list[TradeSignal]:
        return []


class _LegacyStrategy(StrategyExecuter):
    """Old-style strategy: execute(tick) -> TradeSignal | None (no asset_num)."""

    @property
    def id(self) -> str:
        return "legacy_test"

    @property
    def parameter_schema(self):
        return []

    @property
    def subscriptions(self):
        return [Subscription("btcusdt", "1m")]

    async def execute(self, tick: TickData):  # type: ignore[override]
        return None


# ── SignalSide enum ───────────────────────────────────────────────────

def test_signal_side_is_string_enum():
    assert SignalSide.LONG == "long"
    assert SignalSide.SHORT == "short"
    assert SignalSide.BUY == "buy"
    assert SignalSide.SELL == "sell"
    assert SignalSide.CALL == "call"
    assert SignalSide.PUT == "put"


def test_signal_side_can_be_constructed_from_string():
    assert SignalSide("long") is SignalSide.LONG
    assert SignalSide("short") is SignalSide.SHORT


def test_signal_side_invalid_value_raises():
    with pytest.raises(ValueError):
        SignalSide("invalid")


# ── TradeSignal dataclass ─────────────────────────────────────────────

def test_trade_signal_required_fields():
    sig = TradeSignal(
        execute=SignalSide.LONG,
        asset_num=0,
        exchange_num=0,
        market_type="futures",
        amount=0.5,
    )
    assert sig.execute == SignalSide.LONG
    assert sig.asset_num == 0
    assert sig.exchange_num == 0
    assert sig.market_type == "futures"
    assert sig.amount == 0.5


def test_trade_signal_optional_fields_default_to_none():
    sig = TradeSignal(execute=SignalSide.SHORT, asset_num=1, exchange_num=0, market_type="spot", amount=0.3)
    assert sig.tp_pct is None
    assert sig.sl_pct is None
    assert sig.price is None


def test_trade_signal_metadata_defaults_to_empty_dict():
    sig = TradeSignal(execute=SignalSide.LONG, asset_num=0, exchange_num=0, market_type="futures", amount=1.0)
    assert sig.metadata == {}


def test_trade_signal_metadata_instances_are_independent():
    """Each TradeSignal gets its own metadata dict (not shared)."""
    s1 = TradeSignal(execute=SignalSide.LONG, asset_num=0, exchange_num=0, market_type="futures", amount=1.0)
    s2 = TradeSignal(execute=SignalSide.SHORT, asset_num=0, exchange_num=0, market_type="futures", amount=1.0)
    s1.metadata["key"] = "value"
    assert "key" not in s2.metadata


def test_trade_signal_multi_leg_asset_targeting():
    """Multi-leg signals reference different asset_num and exchange_num."""
    leg_long = TradeSignal(execute=SignalSide.LONG, asset_num=0, exchange_num=0, market_type="futures", amount=0.3)
    leg_short = TradeSignal(execute=SignalSide.SHORT, asset_num=1, exchange_num=1, market_type="futures", amount=0.3)
    assert leg_long.asset_num != leg_short.asset_num
    assert leg_long.exchange_num != leg_short.exchange_num


# ── ParameterSchema dataclass ─────────────────────────────────────────

def test_parameter_schema_int_type():
    p = ParameterSchema(name="period", type="int", default=14, min=2.0, max=100.0, description="RSI period")
    assert p.name == "period"
    assert p.type == "int"
    assert p.default == 14
    assert p.min == 2.0
    assert p.max == 100.0
    assert p.description == "RSI period"


def test_parameter_schema_optional_fields_default_to_none():
    p = ParameterSchema(name="flag", type="bool", default=True)
    assert p.min is None
    assert p.max is None
    assert p.description == ""


# ── StrategyAssetConfig dataclass ─────────────────────────────────────

def test_strategy_asset_config_stores_all_fields():
    cfg = StrategyAssetConfig(
        asset_num=1,
        asset_slug="ethusdt",
        exchange="binance",
        timeframe="1h",
        market_type="futures",
        tick_process=False,
    )
    assert cfg.asset_num == 1
    assert cfg.asset_slug == "ethusdt"
    assert cfg.exchange == "binance"
    assert cfg.timeframe == "1h"
    assert cfg.market_type == "futures"
    assert cfg.tick_process is False


# ── StrategyExecuter abstract class ──────────────────────────────────

def test_strategy_executer_cannot_be_instantiated():
    with pytest.raises(TypeError):
        StrategyExecuter()  # type: ignore


def test_modern_strategy_accepts_params_and_assets():
    strategy = _ModernStrategy(
        params={"alpha": 0.1},
        assets=[StrategyAssetConfig(0, "btcusdt", "binance", "1m", "futures", True)],
    )
    assert strategy.params == {"alpha": 0.1}
    assert len(strategy.assets) == 1


def test_strategy_params_default_to_empty_dict():
    strategy = _ModernStrategy()
    assert strategy.params == {}


def test_strategy_assets_default_to_empty_list():
    strategy = _ModernStrategy()
    assert strategy.assets == []


# ── _is_legacy() compatibility shim ─────────────────────────────────

def test_is_legacy_returns_false_for_modern_strategy():
    assert _ModernStrategy._is_legacy() is False


def test_is_legacy_returns_true_for_legacy_strategy():
    assert _LegacyStrategy._is_legacy() is True


def test_is_legacy_based_on_execute_signature():
    """The shim checks whether 'asset_num' appears in execute()'s parameters."""
    import inspect
    modern_sig = inspect.signature(_ModernStrategy.execute)
    legacy_sig = inspect.signature(_LegacyStrategy.execute)
    assert "asset_num" in modern_sig.parameters
    assert "asset_num" not in legacy_sig.parameters
