"""
Integration tests for the run_strategy Celery task (sync wrapper).
These tests execute the task logic directly (without a Celery broker) so they are
fast and require only a Redis connection if decorated with @needs_redis.
Redis-free tests use patched aioredis to verify publish logic.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.data_fetcher import TickData
from app.services.strategy_executer import (
    ExecutionPlan, LegOrder, PriceMethod, SignalAction, AmountMode, StrategyLeg, StrategyExecuter,
)
from app.services.strategy_context import StrategyContext
from app.tasks.strategy import _publish_plan


# ── Helpers ───────────────────────────────────────────────────────────

def _make_tick(close: float = 60_000.0) -> TickData:
    return TickData(
        symbol="btcusdt",
        timeframe="30m",
        time=1_700_000_000_000,
        open=close, high=close * 1.001, low=close * 0.999,
        close=close, volume=100.0,
        market_type="futures",
    )


def _make_leg(leg_num: int = 0, symbol: str = "btcusdt") -> StrategyLeg:
    return StrategyLeg(
        leg_num=leg_num,
        role="primary",
        symbol=symbol,
        exchange="binance",
        market_type="futures",
        timeframe="30m",
        tick_process=(leg_num == 0),
        subscribe_depth=False,
        base_asset="BTC",
        quote_asset="USDT",
        exchange_account_num=0,
    )


def _make_context(close: float = 60_000.0, leg_num: int = 0) -> StrategyContext:
    return StrategyContext(
        tick=_make_tick(close),
        leg_num=leg_num,
        legs=[_make_leg()],
        config_id="cfg-test",
    )


def _make_order(action: SignalAction = SignalAction.OPEN_LONG) -> LegOrder:
    return LegOrder(
        leg_num=0,
        action=action,
        amount=0.5,
        amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED,
        price_method=PriceMethod.MARKET,
    )


# ── _publish_plan ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_publish_plan_writes_to_trade_stream():
    """_publish_plan adds one message to the signals:trade stream."""
    r = AsyncMock()
    r.xadd = AsyncMock(return_value="1700000000000-0")
    ctx = _make_context()
    plan = ExecutionPlan(orders=[_make_order()])
    await _publish_plan(r, plan, "cfg-1", ctx)
    calls = r.xadd.call_args_list
    stream_keys = [c.args[0] for c in calls]
    assert "signals:trade" in stream_keys


@pytest.mark.asyncio
async def test_publish_plan_writes_to_broadcast_stream():
    """_publish_plan also writes to the signals:broadcast stream."""
    r = AsyncMock()
    r.xadd = AsyncMock(return_value="1700000000000-0")
    ctx = _make_context()
    plan = ExecutionPlan(orders=[_make_order()])
    await _publish_plan(r, plan, "cfg-1", ctx)
    calls = r.xadd.call_args_list
    stream_keys = [c.args[0] for c in calls]
    assert "signals:broadcast" in stream_keys


@pytest.mark.asyncio
async def test_publish_plan_fields_contain_orders_json():
    """The 'orders' field in the stream message is a valid JSON list of LegOrder dicts."""
    r = AsyncMock()
    r.xadd = AsyncMock(return_value="1-0")
    ctx = _make_context()
    order = _make_order(action=SignalAction.OPEN_SHORT)
    plan = ExecutionPlan(orders=[order])
    await _publish_plan(r, plan, "cfg-1", ctx)

    # Grab the first call (signals:trade)
    fields = r.xadd.call_args_list[0].args[1]
    orders_list = json.loads(fields["orders"])
    assert len(orders_list) == 1
    assert orders_list[0]["action"] == SignalAction.OPEN_SHORT.value


@pytest.mark.asyncio
async def test_publish_plan_fields_contain_config_id():
    r = AsyncMock()
    r.xadd = AsyncMock(return_value="1-0")
    ctx = _make_context()
    plan = ExecutionPlan(orders=[_make_order()])
    await _publish_plan(r, plan, "cfg-42", ctx)
    fields = r.xadd.call_args_list[0].args[1]
    assert fields["config_id"] == "cfg-42"


@pytest.mark.asyncio
async def test_publish_plan_fields_contain_tick_info():
    r = AsyncMock()
    r.xadd = AsyncMock(return_value="1-0")
    ctx = _make_context(close=55_000.0)
    plan = ExecutionPlan(orders=[_make_order()])
    await _publish_plan(r, plan, "cfg-1", ctx)
    fields = r.xadd.call_args_list[0].args[1]
    assert float(fields["tick_close"]) == pytest.approx(55_000.0)
    assert fields["tick_symbol"] == "btcusdt"


@pytest.mark.asyncio
async def test_publish_plan_multi_leg_orders_serialized():
    """Multiple LegOrders are all present in the JSON."""
    r = AsyncMock()
    r.xadd = AsyncMock(return_value="1-0")
    ctx = _make_context()
    plan = ExecutionPlan(orders=[
        _make_order(action=SignalAction.OPEN_LONG),
        LegOrder(leg_num=1, action=SignalAction.OPEN_SHORT, amount=0.3),
    ])
    await _publish_plan(r, plan, "cfg-1", ctx)
    fields = r.xadd.call_args_list[0].args[1]
    orders_list = json.loads(fields["orders"])
    assert len(orders_list) == 2
    actions = {o["action"] for o in orders_list}
    assert SignalAction.OPEN_LONG.value in actions
    assert SignalAction.OPEN_SHORT.value in actions


@pytest.mark.asyncio
async def test_publish_plan_empty_on_complete_when_none():
    r = AsyncMock()
    r.xadd = AsyncMock(return_value="1-0")
    ctx = _make_context()
    plan = ExecutionPlan(orders=[_make_order()], on_complete=None)
    await _publish_plan(r, plan, "cfg-1", ctx)
    fields = r.xadd.call_args_list[0].args[1]
    assert fields["on_complete"] == ""


@pytest.mark.asyncio
async def test_publish_plan_on_complete_forwarded():
    r = AsyncMock()
    r.xadd = AsyncMock(return_value="1-0")
    ctx = _make_context()
    plan = ExecutionPlan(orders=[_make_order()], on_complete="settle_transfer")
    await _publish_plan(r, plan, "cfg-1", ctx)
    fields = r.xadd.call_args_list[0].args[1]
    assert fields["on_complete"] == "settle_transfer"


# ── Module-level stub strategies (needed so importlib.import_module can find them) ──

class _NoSignalStrategy(StrategyExecuter):
    @property
    def id(self): return "no-signal"
    @property
    def subscriptions(self): return []
    @property
    def parameter_schema(self): return []
    async def execute(self, context): return None


class _SignalStrategy(StrategyExecuter):
    @property
    def id(self): return "signal"
    @property
    def subscriptions(self): return []
    @property
    def parameter_schema(self): return []
    async def execute(self, context):
        return ExecutionPlan(orders=[_make_order()])


class _FailStrategy(StrategyExecuter):
    @property
    def id(self): return "fail"
    @property
    def subscriptions(self): return []
    @property
    def parameter_schema(self): return []
    async def execute(self, context):
        raise RuntimeError("Something broke")


# ── run_strategy task ─────────────────────────────────────────────────

def test_run_strategy_task_no_signal_returns_string():
    """Strategy that returns None → task returns 'No signal'."""
    from app.tasks.strategy import run_strategy

    ctx = _make_context()
    class_path = f"{_NoSignalStrategy.__module__}.{_NoSignalStrategy.__qualname__}"

    mock_redis = AsyncMock()
    mock_redis.delete = AsyncMock()
    mock_redis.xadd = AsyncMock(return_value="1-0")
    mock_redis.aclose = AsyncMock()

    with patch("app.tasks.strategy.aioredis.from_url", AsyncMock(return_value=mock_redis)):
        result = run_strategy(ctx.config_id, class_path, ctx.to_dict(), {})

    assert "No signal" in result


def test_run_strategy_task_publishes_plan_on_signal():
    """Strategy that returns an ExecutionPlan → xadd called on both streams."""
    from app.tasks.strategy import run_strategy

    ctx = _make_context()
    class_path = f"{_SignalStrategy.__module__}.{_SignalStrategy.__qualname__}"

    mock_redis = AsyncMock()
    mock_redis.delete = AsyncMock()
    mock_redis.xadd = AsyncMock(return_value="1-0")
    mock_redis.aclose = AsyncMock()

    with patch("app.tasks.strategy.aioredis.from_url", AsyncMock(return_value=mock_redis)):
        result = run_strategy(ctx.config_id, class_path, ctx.to_dict(), {})

    stream_keys = [c.args[0] for c in mock_redis.xadd.call_args_list]
    assert "signals:trade" in stream_keys
    assert "signals:broadcast" in stream_keys
    assert "published" in result


def test_run_strategy_task_always_releases_lock():
    """Lock key is deleted even if strategy raises an exception."""
    from app.tasks.strategy import run_strategy

    ctx = _make_context()
    class_path = f"{_FailStrategy.__module__}.{_FailStrategy.__qualname__}"

    mock_redis = AsyncMock()
    mock_redis.delete = AsyncMock()
    mock_redis.xadd = AsyncMock(return_value="1-0")
    mock_redis.aclose = AsyncMock()

    with patch("app.tasks.strategy.aioredis.from_url", AsyncMock(return_value=mock_redis)):
        with pytest.raises(RuntimeError):
            run_strategy(ctx.config_id, class_path, ctx.to_dict(), {})

    mock_redis.delete.assert_called_once_with(f"strategy_lock:{ctx.config_id}")


# ── StrategyContext serialization round-trip ─────────────────────────

def test_strategy_context_to_dict_from_dict_round_trip():
    ctx = _make_context(close=50_000.0, leg_num=0)
    ctx_dict = ctx.to_dict()
    restored = StrategyContext.from_dict(ctx_dict)
    assert restored.tick.close == pytest.approx(50_000.0)
    assert restored.leg_num == 0
    assert restored.config_id == ctx.config_id
    assert len(restored.legs) == 1
    assert restored.legs[0].symbol == "btcusdt"


def test_strategy_context_from_dict_reconstructs_legs():
    ctx = StrategyContext(
        tick=_make_tick(),
        leg_num=0,
        legs=[_make_leg(0, "btcusdt"), _make_leg(1, "ethusdt")],
        config_id="cfg-multi",
    )
    restored = StrategyContext.from_dict(ctx.to_dict())
    assert len(restored.legs) == 2
    symbols = [l.symbol for l in restored.legs]
    assert "btcusdt" in symbols
    assert "ethusdt" in symbols
