"""
Unit tests for TradeExecuterProcess:
- Stale message rejection
- _execute_order open/close/same-side logic
- _open_position TP/SL and size calculation
- _close_position PnL persistence math
- _compute_size for various AmountModes
No real Redis or DB — all I/O mocked.
"""
import json
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.strategy_executer import AmountMode, LegOrder, PriceMethod, SignalAction
from app.services.trade_adapter import OrderResult, PositionInfo
from app.services.trade_executer_process import TradeExecuterProcess, _MAX_SIGNAL_AGE_SECONDS


def _make_order(
    leg_num: int = 0,
    action: SignalAction = SignalAction.OPEN_LONG,
    amount: float = 0.5,
    amount_mode: AmountMode = AmountMode.PORTFOLIO_PCT_REALIZED,
    price: float | None = 50_000.0,
    tp_pct: float | None = 0.02,
    sl_pct: float | None = 0.01,
) -> LegOrder:
    return LegOrder(
        leg_num=leg_num,
        action=action,
        amount=amount,
        amount_mode=amount_mode,
        price_method=PriceMethod.MARKET,
        price=price,
        tp_pct=tp_pct,
        sl_pct=sl_pct,
    )


def _make_process(mock_redis: AsyncMock) -> TradeExecuterProcess:
    p = TradeExecuterProcess()
    p._redis = mock_redis
    return p


def _make_adapter(balance: float = 10_000.0, open_position: PositionInfo | None = None) -> AsyncMock:
    adapter = AsyncMock()
    adapter.get_balance = AsyncMock(return_value=balance)
    adapter.get_open_position = AsyncMock(return_value=open_position)
    adapter.open_position = AsyncMock(return_value=OrderResult(
        order_id="ord-1", symbol="btcusdt", side="long",
        price=50_000.0, size=0.1, status="filled",
    ))
    adapter.close_position = AsyncMock(return_value=OrderResult(
        order_id="ord-2", symbol="btcusdt", side="long",
        price=55_000.0, size=0.1, status="filled",
    ))
    return adapter


def _make_db_session(existing_row: MagicMock | None = None) -> AsyncMock:
    result_mock = MagicMock()
    result_mock.scalar_one_or_none = MagicMock(return_value=existing_row)
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result_mock)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


def _make_message_fields(orders: list[LegOrder], ts_offset: float = -1) -> dict:
    """Build a stream message fields dict matching what _publish_plan produces."""
    return {
        "ts": str(time.time() + ts_offset),
        "config_id": "cfg-1",
        "strategy_id": "cfg-1",
        "tick_close": "50000.0",
        "tick_market_type": "futures",
        "on_complete": "",
        "plan_metadata": "{}",
        "orders": json.dumps([o.to_dict() for o in orders]),
    }


# ── Stale message rejection ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_message_discards_stale_signal(mock_redis):
    process = _make_process(mock_redis)
    stale_ts = time.time() - (_MAX_SIGNAL_AGE_SECONDS + 10)
    fields = _make_message_fields([_make_order()], ts_offset=0)
    fields["ts"] = str(stale_ts)
    await process._handle_message("1-0", fields)
    mock_redis.xack.assert_called_once()


@pytest.mark.asyncio
async def test_handle_message_processes_fresh_signal(mock_redis):
    process = _make_process(mock_redis)
    orders = [_make_order()]
    fields = _make_message_fields(orders, ts_offset=-1)

    with patch.object(process, "_resolve_leg", AsyncMock(return_value=("btcusdt", "30m", "futures", "BTC", "USDT"))), \
         patch.object(process, "_resolve_adapter", AsyncMock(return_value=_make_adapter())), \
         patch.object(process, "_execute_order", AsyncMock()) as mock_exec:
        await process._handle_message("2-0", fields)

    mock_exec.assert_called_once()
    mock_redis.xack.assert_called_once()


@pytest.mark.asyncio
async def test_handle_message_skips_empty_orders(mock_redis):
    """Empty orders list → ack without executing anything."""
    process = _make_process(mock_redis)
    fields = _make_message_fields([], ts_offset=-1)
    await process._handle_message("3-0", fields)
    mock_redis.xack.assert_called_once()


@pytest.mark.asyncio
async def test_handle_message_publishes_on_complete_when_set(mock_redis):
    process = _make_process(mock_redis)
    orders = [_make_order()]
    fields = _make_message_fields(orders, ts_offset=-1)
    fields["on_complete"] = "settle_transfer"

    with patch.object(process, "_resolve_leg", AsyncMock(return_value=("btcusdt", "30m", "futures", "BTC", "USDT"))), \
         patch.object(process, "_resolve_adapter", AsyncMock(return_value=_make_adapter())), \
         patch.object(process, "_execute_order", AsyncMock()):
        await process._handle_message("4-0", fields)

    # xadd called twice: once for callbacks stream, once for xack (which is separate)
    assert mock_redis.xadd.called


# ── _execute_order decision logic ─────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_order_opens_position_when_none_exists(mock_redis):
    process = _make_process(mock_redis)
    adapter = _make_adapter(open_position=None)
    order = _make_order(action=SignalAction.OPEN_LONG)

    with patch.object(process, "_open_position", AsyncMock()) as mock_open, \
         patch.object(process, "_close_position", AsyncMock()) as mock_close, \
         patch("app.services.trade_executer_process.SessionLocal", return_value=_make_db_session()):
        await process._execute_order(order, adapter, "strat-1", "btcusdt", "futures", "BTC", "USDT", 50_000.0)

    mock_open.assert_called_once()
    mock_close.assert_not_called()


@pytest.mark.asyncio
async def test_execute_order_closes_opposite_then_opens(mock_redis):
    """Currently SHORT, order is OPEN_LONG → close SHORT then open LONG."""
    process = _make_process(mock_redis)
    existing = PositionInfo("btcusdt", "short", 0.1, 50_000.0, 0.0, 0.0)
    adapter = _make_adapter(open_position=existing)
    order = _make_order(action=SignalAction.OPEN_LONG)

    with patch.object(process, "_open_position", AsyncMock()) as mock_open, \
         patch.object(process, "_close_position", AsyncMock()) as mock_close:
        await process._execute_order(order, adapter, "strat-1", "btcusdt", "futures", "BTC", "USDT", 50_000.0)

    mock_close.assert_called_once()
    mock_open.assert_called_once()


@pytest.mark.asyncio
async def test_execute_order_skips_entry_on_same_side(mock_redis):
    """Already LONG, order is OPEN_LONG → skip."""
    process = _make_process(mock_redis)
    existing = PositionInfo("btcusdt", "long", 0.1, 50_000.0, 0.0, 0.0)
    adapter = _make_adapter(open_position=existing)
    order = _make_order(action=SignalAction.OPEN_LONG)

    with patch.object(process, "_open_position", AsyncMock()) as mock_open, \
         patch.object(process, "_close_position", AsyncMock()) as mock_close:
        await process._execute_order(order, adapter, "strat-1", "btcusdt", "futures", "BTC", "USDT", 50_000.0)

    mock_open.assert_not_called()
    mock_close.assert_not_called()


@pytest.mark.asyncio
async def test_execute_close_order_closes_existing_position(mock_redis):
    """CLOSE_LONG order on existing LONG position → close it."""
    process = _make_process(mock_redis)
    existing = PositionInfo("btcusdt", "long", 0.1, 50_000.0, 0.0, 0.0)
    adapter = _make_adapter(open_position=existing)
    order = _make_order(action=SignalAction.CLOSE_LONG)

    with patch.object(process, "_open_position", AsyncMock()) as mock_open, \
         patch.object(process, "_close_position", AsyncMock()) as mock_close:
        await process._execute_order(order, adapter, "strat-1", "btcusdt", "futures", "BTC", "USDT", 50_000.0)

    mock_close.assert_called_once()
    mock_open.assert_not_called()


@pytest.mark.asyncio
async def test_execute_close_order_ignores_missing_position(mock_redis):
    """CLOSE_LONG when no position exists → no call to _close_position."""
    process = _make_process(mock_redis)
    adapter = _make_adapter(open_position=None)
    order = _make_order(action=SignalAction.CLOSE_LONG)

    with patch.object(process, "_open_position", AsyncMock()) as mock_open, \
         patch.object(process, "_close_position", AsyncMock()) as mock_close:
        await process._execute_order(order, adapter, "strat-1", "btcusdt", "futures", "BTC", "USDT", 50_000.0)

    mock_close.assert_not_called()
    mock_open.assert_not_called()


# ── _open_position size and TP/SL calculation ─────────────────────────

@pytest.mark.asyncio
async def test_open_position_calculates_size_correctly(mock_redis):
    """size = (balance * amount) / price."""
    balance = 10_000.0
    amount = 0.5
    price = 50_000.0
    expected_size = (balance * amount) / price  # = 0.1

    process = _make_process(mock_redis)
    adapter = _make_adapter(balance=balance)
    order = _make_order(action=SignalAction.OPEN_LONG, amount=amount, price=price, tp_pct=None, sl_pct=None)

    with patch("app.services.trade_executer_process.SessionLocal") as MockSession:
        MockSession.return_value = _make_db_session()
        await process._open_position(order, adapter, "strat-1", "btcusdt", "futures", price, "BTC", "USDT")

    adapter.open_position.assert_called_once()
    call_kwargs = adapter.open_position.call_args.kwargs
    assert call_kwargs["size"] == pytest.approx(expected_size)
    assert call_kwargs["price"] == price


@pytest.mark.asyncio
async def test_open_long_tp_price_is_above_entry(mock_redis):
    """LONG: tp_price = entry * (1 + tp_pct)."""
    entry = 50_000.0
    tp_pct = 0.02
    process = _make_process(mock_redis)
    adapter = _make_adapter(balance=10_000.0)
    order = _make_order(action=SignalAction.OPEN_LONG, amount=0.5, price=entry, tp_pct=tp_pct, sl_pct=None)

    with patch("app.services.trade_executer_process.SessionLocal") as MockSession:
        MockSession.return_value = _make_db_session()
        await process._open_position(order, adapter, "strat-1", "btcusdt", "futures", entry, "BTC", "USDT")

    call_kwargs = adapter.open_position.call_args.kwargs
    assert call_kwargs["tp_price"] == pytest.approx(entry * (1 + tp_pct))


@pytest.mark.asyncio
async def test_open_long_sl_price_is_below_entry(mock_redis):
    """LONG: sl_price = entry * (1 - sl_pct)."""
    entry = 50_000.0
    sl_pct = 0.01
    process = _make_process(mock_redis)
    adapter = _make_adapter(balance=10_000.0)
    order = _make_order(action=SignalAction.OPEN_LONG, amount=0.5, price=entry, tp_pct=None, sl_pct=sl_pct)

    with patch("app.services.trade_executer_process.SessionLocal") as MockSession:
        MockSession.return_value = _make_db_session()
        await process._open_position(order, adapter, "strat-1", "btcusdt", "futures", entry, "BTC", "USDT")

    call_kwargs = adapter.open_position.call_args.kwargs
    assert call_kwargs["sl_price"] == pytest.approx(entry * (1 - sl_pct))


@pytest.mark.asyncio
async def test_open_short_tp_price_is_below_entry(mock_redis):
    """SHORT: tp_price = entry * (1 - tp_pct)."""
    entry = 50_000.0
    tp_pct = 0.02
    process = _make_process(mock_redis)
    adapter = _make_adapter(balance=10_000.0)
    order = _make_order(action=SignalAction.OPEN_SHORT, amount=0.5, price=entry, tp_pct=tp_pct, sl_pct=None)

    with patch("app.services.trade_executer_process.SessionLocal") as MockSession:
        MockSession.return_value = _make_db_session()
        await process._open_position(order, adapter, "strat-1", "btcusdt", "futures", entry, "BTC", "USDT")

    call_kwargs = adapter.open_position.call_args.kwargs
    assert call_kwargs["tp_price"] == pytest.approx(entry * (1 - tp_pct))


@pytest.mark.asyncio
async def test_open_short_sl_price_is_above_entry(mock_redis):
    """SHORT: sl_price = entry * (1 + sl_pct)."""
    entry = 50_000.0
    sl_pct = 0.01
    process = _make_process(mock_redis)
    adapter = _make_adapter(balance=10_000.0)
    order = _make_order(action=SignalAction.OPEN_SHORT, amount=0.5, price=entry, tp_pct=None, sl_pct=sl_pct)

    with patch("app.services.trade_executer_process.SessionLocal") as MockSession:
        MockSession.return_value = _make_db_session()
        await process._open_position(order, adapter, "strat-1", "btcusdt", "futures", entry, "BTC", "USDT")

    call_kwargs = adapter.open_position.call_args.kwargs
    assert call_kwargs["sl_price"] == pytest.approx(entry * (1 + sl_pct))


@pytest.mark.asyncio
async def test_open_with_no_tp_sl_passes_none(mock_redis):
    process = _make_process(mock_redis)
    adapter = _make_adapter(balance=10_000.0)
    order = _make_order(action=SignalAction.OPEN_LONG, amount=0.5, price=50_000.0, tp_pct=None, sl_pct=None)

    with patch("app.services.trade_executer_process.SessionLocal") as MockSession:
        MockSession.return_value = _make_db_session()
        await process._open_position(order, adapter, "strat-1", "btcusdt", "futures", 50_000.0, "BTC", "USDT")

    call_kwargs = adapter.open_position.call_args.kwargs
    assert call_kwargs["tp_price"] is None
    assert call_kwargs["sl_price"] is None


# ── _close_position PnL calculation ──────────────────────────────────

@pytest.mark.asyncio
async def test_close_long_pnl_is_exit_minus_entry_times_size(mock_redis):
    """Long PnL = (exit - entry) * size."""
    process = _make_process(mock_redis)
    entry_price = 50_000.0
    exit_price = 55_000.0
    size = 0.1
    expected_pnl = (exit_price - entry_price) * size  # 500.0

    adapter = AsyncMock()
    adapter.close_position = AsyncMock(return_value=OrderResult(
        order_id="c1", symbol="btcusdt", side="long", price=exit_price, size=size, status="filled",
    ))

    mock_row = MagicMock()
    mock_row.id = 1
    mock_row.entry_price = entry_price
    mock_row.size = size
    mock_row.side = "long"

    with patch("app.services.trade_executer_process.SessionLocal") as MockSession:
        MockSession.return_value = _make_db_session(existing_row=mock_row)
        await process._close_position(adapter, "strat-1", "btcusdt", "long", exit_price, "signal", "BTC", "USDT")

    assert mock_row.pnl == pytest.approx(expected_pnl)
    assert mock_row.pnl_pct == pytest.approx(expected_pnl / (entry_price * size))
    assert mock_row.exit_price == exit_price
    assert mock_row.is_open is False


@pytest.mark.asyncio
async def test_close_short_pnl_is_entry_minus_exit_times_size(mock_redis):
    """Short PnL = (entry - exit) * size."""
    process = _make_process(mock_redis)
    entry_price = 55_000.0
    exit_price = 50_000.0
    size = 0.1
    expected_pnl = (entry_price - exit_price) * size  # 500.0

    adapter = AsyncMock()
    adapter.close_position = AsyncMock(return_value=OrderResult(
        order_id="c2", symbol="btcusdt", side="short", price=exit_price, size=size, status="filled",
    ))

    mock_row = MagicMock()
    mock_row.id = 2
    mock_row.entry_price = entry_price
    mock_row.size = size
    mock_row.side = "short"

    with patch("app.services.trade_executer_process.SessionLocal") as MockSession:
        MockSession.return_value = _make_db_session(existing_row=mock_row)
        await process._close_position(adapter, "strat-1", "btcusdt", "short", exit_price, "tp", "BTC", "USDT")

    assert mock_row.pnl == pytest.approx(expected_pnl)
    assert mock_row.exit_reason == "tp"


@pytest.mark.asyncio
async def test_close_long_loss_is_negative_pnl(mock_redis):
    process = _make_process(mock_redis)
    entry = 50_000.0
    exit_price = 49_000.0
    size = 0.1
    expected_pnl = (exit_price - entry) * size  # -100.0

    adapter = AsyncMock()
    adapter.close_position = AsyncMock(return_value=OrderResult(
        order_id="c3", symbol="btcusdt", side="long", price=exit_price, size=size, status="filled",
    ))
    mock_row = MagicMock()
    mock_row.id = 3
    mock_row.entry_price = entry
    mock_row.size = size
    mock_row.side = "long"

    with patch("app.services.trade_executer_process.SessionLocal") as MockSession:
        MockSession.return_value = _make_db_session(existing_row=mock_row)
        await process._close_position(adapter, "strat-1", "btcusdt", "long", exit_price, "sl", "BTC", "USDT")

    assert mock_row.pnl == pytest.approx(expected_pnl)
    assert mock_row.pnl < 0


# ── _compute_size ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_compute_size_portfolio_pct_realized(mock_redis):
    """PORTFOLIO_PCT_REALIZED: size = (balance * amount) / price."""
    process = _make_process(mock_redis)
    adapter = _make_adapter(balance=10_000.0)
    order = _make_order(amount=0.5, amount_mode=AmountMode.PORTFOLIO_PCT_REALIZED, price=50_000.0)
    size = await process._compute_size(order, adapter, "cfg-1", "btcusdt", 50_000.0)
    assert size == pytest.approx(0.1)  # (10000 * 0.5) / 50000


@pytest.mark.asyncio
async def test_compute_size_units_returns_amount_directly(mock_redis):
    """UNITS: returns order.amount directly."""
    process = _make_process(mock_redis)
    adapter = _make_adapter(balance=10_000.0)
    order = _make_order(amount=3.0, amount_mode=AmountMode.UNITS, price=50_000.0)
    size = await process._compute_size(order, adapter, "cfg-1", "btcusdt", 50_000.0)
    assert size == pytest.approx(3.0)
