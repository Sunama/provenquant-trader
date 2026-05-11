"""
Unit tests for the StrategyExecuter base class and related dataclasses.
No external services required.
"""
import pytest
from app.services.strategy_executer import (
    AmountMode,
    ExecutionPlan,
    LegOrder,
    ParameterSchema,
    PriceMethod,
    SignalAction,
    StrategyExecuter,
    StrategyLeg,
)
from app.services.data_fetcher import Subscription
from app.services.strategy_context import StrategyContext


# ── Minimal concrete implementation for testing ───────────────────────

class _ConcreteStrategy(StrategyExecuter):
    @property
    def id(self) -> str:
        return "concrete_test"

    @property
    def parameter_schema(self):
        return []

    @property
    def subscriptions(self):
        return [Subscription(symbol="btcusdt", timeframe="1m")]

    async def execute(self, context: StrategyContext):
        return None


# ── SignalAction enum ─────────────────────────────────────────────────

def test_signal_action_values():
    assert SignalAction.OPEN_LONG == "open_long"
    assert SignalAction.CLOSE_LONG == "close_long"
    assert SignalAction.OPEN_SHORT == "open_short"
    assert SignalAction.CLOSE_SHORT == "close_short"


def test_signal_action_from_string():
    assert SignalAction("open_long") is SignalAction.OPEN_LONG
    assert SignalAction("close_short") is SignalAction.CLOSE_SHORT


def test_signal_action_invalid_value_raises():
    with pytest.raises(ValueError):
        SignalAction("long")  # old value, no longer valid


# ── PriceMethod and AmountMode enums ─────────────────────────────────

def test_price_method_values():
    assert PriceMethod.MARKET == "market"
    assert PriceMethod.LIMIT == "limit"


def test_amount_mode_values():
    assert AmountMode.PORTFOLIO_PCT_REALIZED == "portfolio_pct_realized"
    assert AmountMode.PORTFOLIO_PCT_UNREALIZED == "portfolio_pct_unrealized"
    assert AmountMode.UNITS == "units"
    assert AmountMode.RATIO_TO_LEG == "ratio_to_leg"


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


# ── StrategyLeg dataclass ─────────────────────────────────────────────

def test_strategy_leg_stores_required_fields():
    leg = StrategyLeg(
        leg_num=0,
        role="primary",
        symbol="btcusdt",
        exchange="binance",
        market_type="futures",
        timeframe="30m",
        tick_process=True,
    )
    assert leg.leg_num == 0
    assert leg.role == "primary"
    assert leg.symbol == "btcusdt"
    assert leg.exchange == "binance"
    assert leg.market_type == "futures"
    assert leg.timeframe == "30m"
    assert leg.tick_process is True


def test_strategy_leg_optional_fields_have_defaults():
    leg = StrategyLeg(
        leg_num=1, role="hedge", symbol="ethusdt",
        exchange="binance", market_type="futures", timeframe="1h", tick_process=False,
    )
    assert leg.subscribe_depth is False
    assert leg.base_asset == ""
    assert leg.quote_asset == ""
    assert leg.exchange_account_num == 0


# ── LegOrder dataclass ────────────────────────────────────────────────

def test_leg_order_required_fields():
    order = LegOrder(leg_num=0, action=SignalAction.OPEN_LONG, amount=0.5)
    assert order.leg_num == 0
    assert order.action == SignalAction.OPEN_LONG
    assert order.amount == 0.5


def test_leg_order_optional_fields_have_defaults():
    order = LegOrder(leg_num=0, action=SignalAction.OPEN_LONG, amount=0.5)
    assert order.amount_mode == AmountMode.PORTFOLIO_PCT_REALIZED
    assert order.price_method == PriceMethod.MARKET
    assert order.price is None
    assert order.tp_pct is None
    assert order.sl_pct is None
    assert order.reference_leg is None
    assert order.metadata == {}


def test_leg_order_metadata_instances_are_independent():
    o1 = LegOrder(leg_num=0, action=SignalAction.OPEN_LONG, amount=0.5)
    o2 = LegOrder(leg_num=1, action=SignalAction.OPEN_SHORT, amount=0.5)
    o1.metadata["key"] = "value"
    assert "key" not in o2.metadata


def test_leg_order_to_dict_round_trips():
    order = LegOrder(
        leg_num=0,
        action=SignalAction.OPEN_LONG,
        amount=0.5,
        amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED,
        price_method=PriceMethod.LIMIT,
        price=50_000.0,
        tp_pct=0.02,
        sl_pct=0.01,
    )
    restored = LegOrder.from_dict(order.to_dict())
    assert restored.leg_num == order.leg_num
    assert restored.action == order.action
    assert restored.amount == order.amount
    assert restored.price == order.price
    assert restored.tp_pct == order.tp_pct
    assert restored.sl_pct == order.sl_pct


def test_leg_order_from_dict_handles_optional_nulls():
    d = {
        "leg_num": 0,
        "action": "open_short",
        "amount": 0.3,
        "amount_mode": "portfolio_pct_realized",
        "reference_leg": None,
        "price_method": "market",
        "price": None,
        "tp_pct": None,
        "sl_pct": None,
        "metadata": {},
    }
    order = LegOrder.from_dict(d)
    assert order.action == SignalAction.OPEN_SHORT
    assert order.price is None
    assert order.reference_leg is None


# ── ExecutionPlan dataclass ───────────────────────────────────────────

def test_execution_plan_stores_orders():
    orders = [LegOrder(leg_num=0, action=SignalAction.OPEN_LONG, amount=0.5)]
    plan = ExecutionPlan(orders=orders)
    assert len(plan.orders) == 1
    assert plan.on_complete is None
    assert plan.metadata == {}


def test_execution_plan_to_dict_round_trips():
    orders = [
        LegOrder(leg_num=0, action=SignalAction.OPEN_LONG, amount=0.5),
        LegOrder(leg_num=1, action=SignalAction.OPEN_SHORT, amount=0.5),
    ]
    plan = ExecutionPlan(orders=orders, on_complete="settle", metadata={"tag": "test"})
    restored = ExecutionPlan.from_dict(plan.to_dict())
    assert len(restored.orders) == 2
    assert restored.on_complete == "settle"
    assert restored.metadata == {"tag": "test"}


def test_execution_plan_multi_leg():
    plan = ExecutionPlan(orders=[
        LegOrder(leg_num=0, action=SignalAction.OPEN_LONG, amount=0.3),
        LegOrder(leg_num=1, action=SignalAction.OPEN_SHORT, amount=0.3),
    ])
    assert plan.orders[0].leg_num == 0
    assert plan.orders[1].leg_num == 1


# ── StrategyExecuter abstract class ──────────────────────────────────

def test_strategy_executer_cannot_be_instantiated():
    with pytest.raises(TypeError):
        StrategyExecuter()  # type: ignore


def test_concrete_strategy_can_be_instantiated():
    s = _ConcreteStrategy()
    assert s.id == "concrete_test"
    assert s.params == {}
    assert s.legs == []
    assert s.config_id == ""


def test_strategy_executer_accepts_params_and_legs():
    leg = StrategyLeg(
        leg_num=0, role="primary", symbol="btcusdt",
        exchange="binance", market_type="futures", timeframe="30m", tick_process=True,
    )
    s = _ConcreteStrategy(params={"period": 14}, legs=[leg])
    assert s.params == {"period": 14}
    assert len(s.legs) == 1


def test_strategy_executer_params_default_to_empty_dict():
    s = _ConcreteStrategy()
    assert s.params == {}


def test_strategy_executer_legs_default_to_empty_list():
    s = _ConcreteStrategy()
    assert s.legs == []
