"""
Unit tests for DataCollector:
- Static parser functions (_parse_liquidation, _parse_agg_trade, _ms_to_dt)
- Individual flush methods with mocked Redis and DB session
No real database or Redis connection required.
"""
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.services.data_collector import DefaultDataCollector, _ms_to_dt


# ── _ms_to_dt() ───────────────────────────────────────────────────────

def test_ms_to_dt_converts_milliseconds_to_utc_datetime():
    dt = _ms_to_dt(0)
    assert dt == datetime(1970, 1, 1, tzinfo=timezone.utc)


def test_ms_to_dt_known_timestamp():
    # 2023-11-14T00:00:00Z = 1699920000000 ms
    dt = _ms_to_dt(1_699_920_000_000)
    assert dt.year == 2023
    assert dt.month == 11
    assert dt.day == 14
    assert dt.tzinfo == timezone.utc


def test_ms_to_dt_returns_timezone_aware():
    dt = _ms_to_dt(1_700_000_000_000)
    assert dt.tzinfo is not None


# ── Static parsers ────────────────────────────────────────────────────

def test_parse_liquidation_maps_all_fields():
    fields = {
        "symbol": "btcusdt",
        "exchange": "binance",
        "time": "1700000000000",
        "side": "long_liq",
        "price": "50000.0",
        "quantity": "1.5",
    }
    row = DefaultDataCollector._parse_liquidation(fields)
    assert row["symbol"] == "btcusdt"
    assert row["exchange"] == "binance"
    assert row["side"] == "long_liq"
    assert row["price"] == pytest.approx(50_000.0)
    assert row["quantity"] == pytest.approx(1.5)
    assert isinstance(row["time"], datetime)


def test_parse_agg_trade_maps_all_fields():
    fields = {
        "symbol": "ethusdt",
        "exchange": "binance",
        "time": "1700000000000",
        "price": "3000.0",
        "quantity": "0.5",
        "is_buyer_maker": "True",
    }
    row = DefaultDataCollector._parse_agg_trade(fields)
    assert row["symbol"] == "ethusdt"
    assert row["price"] == pytest.approx(3_000.0)
    assert row["quantity"] == pytest.approx(0.5)
    assert row["is_buyer_maker"] is True


def test_parse_agg_trade_is_buyer_maker_false():
    fields = {
        "symbol": "btcusdt", "exchange": "binance",
        "time": "0", "price": "1.0", "quantity": "1.0",
        "is_buyer_maker": "False",
    }
    row = DefaultDataCollector._parse_agg_trade(fields)
    assert row["is_buyer_maker"] is False


def test_parse_agg_trade_missing_is_buyer_maker_defaults_false():
    fields = {
        "symbol": "btcusdt", "exchange": "binance",
        "time": "0", "price": "1.0", "quantity": "1.0",
    }
    row = DefaultDataCollector._parse_agg_trade(fields)
    assert row["is_buyer_maker"] is False


# ── _flush_ticks() ────────────────────────────────────────────────────

def _make_db_session() -> AsyncMock:
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


@pytest.mark.asyncio
async def test_flush_ticks_returns_zero_when_no_keys():
    collector = DefaultDataCollector()
    mock_r = AsyncMock()
    mock_r.keys = AsyncMock(return_value=[])
    db = _make_db_session()
    count = await collector._flush_ticks(mock_r, db)
    assert count == 0
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_flush_ticks_reads_and_deletes_each_key():
    collector = DefaultDataCollector()
    tick_json = json.dumps({
        "symbol": "btcusdt", "timeframe": "1m",
        "time": 1_700_000_000_000,
        "open": 50_000.0, "high": 50_100.0, "low": 49_900.0,
        "close": 50_050.0, "volume": 100.0,
    })
    mock_r = AsyncMock()
    mock_r.keys = AsyncMock(return_value=["tick:btcusdt:1m"])
    mock_r.lrange = AsyncMock(return_value=[tick_json])
    mock_r.delete = AsyncMock()
    db = _make_db_session()
    count = await collector._flush_ticks(mock_r, db)
    assert count == 1
    mock_r.delete.assert_called_once_with("tick:btcusdt:1m")
    db.execute.assert_called_once()


@pytest.mark.asyncio
async def test_flush_ticks_skips_malformed_json():
    collector = DefaultDataCollector()
    mock_r = AsyncMock()
    mock_r.keys = AsyncMock(return_value=["tick:btcusdt:1m"])
    mock_r.lrange = AsyncMock(return_value=["{bad json}", "also bad"])
    mock_r.delete = AsyncMock()
    db = _make_db_session()
    count = await collector._flush_ticks(mock_r, db)
    assert count == 0  # bad ticks skipped, no DB write


# ── _flush_funding_rates() ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_flush_funding_rates_reads_redis_set():
    collector = DefaultDataCollector()
    funding_json = json.dumps({
        "symbol": "btcusdt", "exchange": "binance",
        "time": 1_700_000_000_000, "rate": 0.0001,
    })
    mock_r = AsyncMock()
    mock_r.keys = AsyncMock(return_value=["funding:btcusdt:binance"])
    mock_r.get = AsyncMock(return_value=funding_json)
    db = _make_db_session()
    count = await collector._flush_funding_rates(mock_r, db)
    assert count == 1
    db.execute.assert_called_once()


@pytest.mark.asyncio
async def test_flush_funding_rates_skips_null_key():
    collector = DefaultDataCollector()
    mock_r = AsyncMock()
    mock_r.keys = AsyncMock(return_value=["funding:btcusdt:binance"])
    mock_r.get = AsyncMock(return_value=None)  # key expired
    db = _make_db_session()
    count = await collector._flush_funding_rates(mock_r, db)
    assert count == 0


# ── _flush_stream() ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_flush_stream_returns_zero_when_no_messages():
    collector = DefaultDataCollector()
    mock_r = AsyncMock()
    mock_r.xgroup_create = AsyncMock(side_effect=Exception("BUSYGROUP already exists"))
    mock_r.xreadgroup = AsyncMock(return_value=None)
    db = _make_db_session()
    count = await collector._flush_stream(mock_r, db, "liquidations:buffer",
                                          DefaultDataCollector._parse_liquidation, MagicMock())
    assert count == 0
    mock_r.xack.assert_not_called()


@pytest.mark.asyncio
async def test_flush_stream_acks_messages_after_insert():
    collector = DefaultDataCollector()
    fields = {
        "symbol": "btcusdt", "exchange": "binance",
        "time": "1700000000000", "side": "long_liq",
        "price": "50000.0", "quantity": "1.0",
    }
    mock_r = AsyncMock()
    mock_r.xgroup_create = AsyncMock(side_effect=Exception("BUSYGROUP"))
    mock_r.xreadgroup = AsyncMock(return_value=[
        ["liquidations:buffer", [("1-0", fields)]]
    ])
    mock_r.xack = AsyncMock()
    db = _make_db_session()

    from app.db.models.liquidation import Liquidation
    count = await collector._flush_stream(mock_r, db, "liquidations:buffer",
                                          DefaultDataCollector._parse_liquidation, Liquidation)
    assert count == 1
    mock_r.xack.assert_called_once()
    ack_args = mock_r.xack.call_args.args
    assert "1-0" in ack_args


@pytest.mark.asyncio
async def test_flush_stream_acks_bad_message_to_avoid_redelivery_loop():
    """Even unparseable messages should be ACKed so they don't block the queue."""
    collector = DefaultDataCollector()
    bad_fields = {"missing": "required fields"}  # will fail _parse_liquidation
    mock_r = AsyncMock()
    mock_r.xgroup_create = AsyncMock(side_effect=Exception("BUSYGROUP"))
    mock_r.xreadgroup = AsyncMock(return_value=[
        ["liquidations:buffer", [("2-0", bad_fields)]]
    ])
    mock_r.xack = AsyncMock()
    db = _make_db_session()

    from app.db.models.liquidation import Liquidation
    await collector._flush_stream(mock_r, db, "liquidations:buffer",
                                  DefaultDataCollector._parse_liquidation, Liquidation)
    mock_r.xack.assert_called_once()


# ── Full collect() flow ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_collect_orchestrates_all_flush_methods():
    """collect() should call each flush method and return total count."""
    collector = DefaultDataCollector()
    with patch.object(collector, "_flush_ticks", AsyncMock(return_value=5)), \
         patch.object(collector, "_flush_funding_rates", AsyncMock(return_value=3)), \
         patch.object(collector, "_flush_mark_prices", AsyncMock(return_value=2)), \
         patch.object(collector, "_flush_open_interest", AsyncMock(return_value=1)), \
         patch.object(collector, "_flush_stream", AsyncMock(return_value=0)), \
         patch("app.services.data_collector.aioredis") as mock_aioredis, \
         patch("app.services.data_collector.SessionLocal") as MockSession:
        mock_r = AsyncMock()
        mock_r.aclose = AsyncMock()
        mock_aioredis.from_url = AsyncMock(return_value=mock_r)
        MockSession.return_value = _make_db_session()
        total = await collector.collect()

    assert total == 5 + 3 + 2 + 1 + 0 + 0  # two stream calls return 0
