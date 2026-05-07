"""
Unit tests for TradeExecuterProcess:
- Stale signal rejection
- Open/close decision logic
- TP/SL and size calculation
- PnL persistence math
No real Redis or DB — all I/O mocked.
"""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.strategy_executer import SignalSide, TradeSignal
from app.services.trade_adapter import OrderResult, PositionInfo
from app.services.trade_executer_process import TradeExecuterProcess, _MAX_SIGNAL_AGE_SECONDS


def _make_signal(
    execute: SignalSide = SignalSide.LONG,
    asset_num: int = 0,
    amount: float = 0.5,
    tp_pct: float | None = 0.02,
    sl_pct: float | None = 0.01,
    price: float | None = 50_000.0,
) -> TradeSignal:
    return TradeSignal(
        execute=execute,
        asset_num=asset_num,
        exchange_num=0,
        market_type="futures",
        amount=amount,
        tp_pct=tp_pct,
        sl_pct=sl_pct,
        price=price,
        metadata={"asset_slug": "btcusdt", "timeframe": "30m"},
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
        order_id="ord-1", asset_slug="btcusdt", side="long",
        price=50_000.0, size=0.1, status="filled",
    ))
    adapter.close_position = AsyncMock(return_value=OrderResult(
        order_id="ord-2", asset_slug="btcusdt", side="long",
        price=55_000.0, size=0.1, status="filled",
    ))
    return adapter


def _make_db_session(existing_row: MagicMock | None = None) -> AsyncMock:
    """AsyncMock of an SQLAlchemy async session used as a context manager."""
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


# ── Stale signal rejection ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_signal_discards_stale_signal(mock_redis):
    process = _make_process(mock_redis)
    stale_ts = time.time() - (_MAX_SIGNAL_AGE_SECONDS + 10)
    fields = {
        "ts": str(stale_ts),
        "config_id": "cfg-1",
        "strategy_id": "strat-1",
        "asset_num": "0",
        "exchange_num": "0",
        "execute": "long",
        "market_type": "futures",
        "amount": "0.5",
        "price": "50000",
    }
    await process._handle_signal("1-0", fields)
    mock_redis.xack.assert_called_once()


@pytest.mark.asyncio
async def test_handle_signal_processes_fresh_signal(mock_redis):
    process = _make_process(mock_redis)
    fresh_ts = time.time() - 1  # 1 second old
    fields = {
        "ts": str(fresh_ts),
        "config_id": "cfg-1",
        "strategy_id": "strat-1",
        "asset_num": "0",
        "exchange_num": "0",
        "execute": "long",
        "market_type": "futures",
        "amount": "0.5",
        "price": "50000",
        "tp_pct": "0.02",
        "sl_pct": "0.01",
    }
    mock_execute = AsyncMock()
    with patch.object(process, "_resolve_asset", AsyncMock(return_value=("btcusdt", "30m"))), \
         patch.object(process, "_resolve_adapter", AsyncMock(return_value=_make_adapter())), \
         patch.object(process, "_execute_signal", mock_execute), \
         patch("app.services.trade_executer_process.SessionLocal", return_value=_make_db_session()):
        await process._handle_signal("2-0", fields)
    mock_execute.assert_called_once()


# ── _execute_signal decision logic ───────────────────────────────────

@pytest.mark.asyncio
async def test_execute_signal_opens_position_when_none_exists(mock_redis):
    process = _make_process(mock_redis)
    adapter = _make_adapter(open_position=None)
    signal = _make_signal(execute=SignalSide.LONG, price=50_000.0)

    with patch.object(process, "_open_position", AsyncMock()) as mock_open, \
         patch.object(process, "_close_position", AsyncMock()) as mock_close, \
         patch("app.services.trade_executer_process.SessionLocal", return_value=_make_db_session()):
        await process._execute_signal(signal, adapter, "strat-1", "btcusdt", 50_000.0)

    mock_open.assert_called_once()
    mock_close.assert_not_called()


@pytest.mark.asyncio
async def test_execute_signal_closes_opposite_then_opens(mock_redis):
    process = _make_process(mock_redis)
    # Currently SHORT, signal is LONG → should close SHORT then open LONG
    existing = PositionInfo("btcusdt", "short", 0.1, 50_000.0, 0.0, 0.0)
    adapter = _make_adapter(open_position=existing)
    signal = _make_signal(execute=SignalSide.LONG, price=50_000.0)

    with patch.object(process, "_open_position", AsyncMock()) as mock_open, \
         patch.object(process, "_close_position", AsyncMock()) as mock_close:
        await process._execute_signal(signal, adapter, "strat-1", "btcusdt", 50_000.0)

    mock_close.assert_called_once()
    mock_open.assert_called_once()


@pytest.mark.asyncio
async def test_execute_signal_skips_entry_on_same_side(mock_redis):
    process = _make_process(mock_redis)
    existing = PositionInfo("btcusdt", "long", 0.1, 50_000.0, 0.0, 0.0)
    adapter = _make_adapter(open_position=existing)
    signal = _make_signal(execute=SignalSide.LONG, price=50_000.0)

    with patch.object(process, "_open_position", AsyncMock()) as mock_open, \
         patch.object(process, "_close_position", AsyncMock()) as mock_close:
        await process._execute_signal(signal, adapter, "strat-1", "btcusdt", 50_000.0)

    mock_open.assert_not_called()
    mock_close.assert_not_called()


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
    signal = _make_signal(execute=SignalSide.LONG, amount=amount, price=price, tp_pct=None, sl_pct=None)

    with patch("app.services.trade_executer_process.SessionLocal") as MockSession:
        MockSession.return_value = _make_db_session()
        await process._open_position(adapter, "strat-1", "btcusdt", signal, price)

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
    signal = _make_signal(execute=SignalSide.LONG, amount=0.5, price=entry, tp_pct=tp_pct, sl_pct=None)

    with patch("app.services.trade_executer_process.SessionLocal") as MockSession:
        MockSession.return_value = _make_db_session()
        await process._open_position(adapter, "strat-1", "btcusdt", signal, entry)

    call_kwargs = adapter.open_position.call_args.kwargs
    assert call_kwargs["tp_price"] == pytest.approx(entry * (1 + tp_pct))


@pytest.mark.asyncio
async def test_open_long_sl_price_is_below_entry(mock_redis):
    """LONG: sl_price = entry * (1 - sl_pct)."""
    entry = 50_000.0
    sl_pct = 0.01
    process = _make_process(mock_redis)
    adapter = _make_adapter(balance=10_000.0)
    signal = _make_signal(execute=SignalSide.LONG, amount=0.5, price=entry, tp_pct=None, sl_pct=sl_pct)

    with patch("app.services.trade_executer_process.SessionLocal") as MockSession:
        MockSession.return_value = _make_db_session()
        await process._open_position(adapter, "strat-1", "btcusdt", signal, entry)

    call_kwargs = adapter.open_position.call_args.kwargs
    assert call_kwargs["sl_price"] == pytest.approx(entry * (1 - sl_pct))


@pytest.mark.asyncio
async def test_open_short_tp_price_is_below_entry(mock_redis):
    """SHORT: tp_price = entry * (1 - tp_pct)."""
    entry = 50_000.0
    tp_pct = 0.02
    process = _make_process(mock_redis)
    adapter = _make_adapter(balance=10_000.0)
    signal = _make_signal(execute=SignalSide.SHORT, amount=0.5, price=entry, tp_pct=tp_pct, sl_pct=None)

    with patch("app.services.trade_executer_process.SessionLocal") as MockSession:
        MockSession.return_value = _make_db_session()
        await process._open_position(adapter, "strat-1", "btcusdt", signal, entry)

    call_kwargs = adapter.open_position.call_args.kwargs
    assert call_kwargs["tp_price"] == pytest.approx(entry * (1 - tp_pct))


@pytest.mark.asyncio
async def test_open_short_sl_price_is_above_entry(mock_redis):
    """SHORT: sl_price = entry * (1 + sl_pct)."""
    entry = 50_000.0
    sl_pct = 0.01
    process = _make_process(mock_redis)
    adapter = _make_adapter(balance=10_000.0)
    signal = _make_signal(execute=SignalSide.SHORT, amount=0.5, price=entry, tp_pct=None, sl_pct=sl_pct)

    with patch("app.services.trade_executer_process.SessionLocal") as MockSession:
        MockSession.return_value = _make_db_session()
        await process._open_position(adapter, "strat-1", "btcusdt", signal, entry)

    call_kwargs = adapter.open_position.call_args.kwargs
    assert call_kwargs["sl_price"] == pytest.approx(entry * (1 + sl_pct))


@pytest.mark.asyncio
async def test_open_with_no_tp_sl_passes_none(mock_redis):
    process = _make_process(mock_redis)
    adapter = _make_adapter(balance=10_000.0)
    signal = _make_signal(execute=SignalSide.LONG, amount=0.5, price=50_000.0, tp_pct=None, sl_pct=None)

    with patch("app.services.trade_executer_process.SessionLocal") as MockSession:
        MockSession.return_value = _make_db_session()
        await process._open_position(adapter, "strat-1", "btcusdt", signal, 50_000.0)

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
        order_id="c1", asset_slug="btcusdt", side="long",
        price=exit_price, size=size, status="filled",
    ))

    mock_row = MagicMock()
    mock_row.id = 1
    mock_row.entry_price = entry_price
    mock_row.size = size
    mock_row.side = "long"

    with patch("app.services.trade_executer_process.SessionLocal") as MockSession:
        MockSession.return_value = _make_db_session(existing_row=mock_row)
        await process._close_position(adapter, "strat-1", "btcusdt", "long", exit_price, "signal")

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
        order_id="c2", asset_slug="btcusdt", side="short",
        price=exit_price, size=size, status="filled",
    ))

    mock_row = MagicMock()
    mock_row.id = 2
    mock_row.entry_price = entry_price
    mock_row.size = size
    mock_row.side = "short"

    with patch("app.services.trade_executer_process.SessionLocal") as MockSession:
        MockSession.return_value = _make_db_session(existing_row=mock_row)
        await process._close_position(adapter, "strat-1", "btcusdt", "short", exit_price, "tp")

    assert mock_row.pnl == pytest.approx(expected_pnl)
    assert mock_row.exit_reason == "tp"


@pytest.mark.asyncio
async def test_close_long_loss_is_negative_pnl(mock_redis):
    """Long trade closed at a loss → negative PnL."""
    process = _make_process(mock_redis)
    entry = 50_000.0
    exit_price = 49_000.0
    size = 0.1
    expected_pnl = (exit_price - entry) * size  # -100.0

    adapter = AsyncMock()
    adapter.close_position = AsyncMock(return_value=OrderResult(
        order_id="c3", asset_slug="btcusdt", side="long",
        price=exit_price, size=size, status="filled",
    ))
    mock_row = MagicMock()
    mock_row.id = 3
    mock_row.entry_price = entry
    mock_row.size = size
    mock_row.side = "long"

    with patch("app.services.trade_executer_process.SessionLocal") as MockSession:
        MockSession.return_value = _make_db_session(existing_row=mock_row)
        await process._close_position(adapter, "strat-1", "btcusdt", "long", exit_price, "sl")

    assert mock_row.pnl == pytest.approx(expected_pnl)
    assert mock_row.pnl < 0
