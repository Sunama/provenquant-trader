# CLAUDE.md — provenquant-trader

## What This Is

Standalone paper-trading system. Can run independently or integrate with the ProvenQuant main platform to pull signals. Built on the same tech stack as `witzh/backend`.

## Quick Start

```bash
cp .env.template .env        # fill in secrets
sudo docker compose up -d    # starts postgres, redis, rabbitmq, backend, workers
sudo docker compose exec backend alembic upgrade head
```

## Key Commands

```bash
# Run migrations
sudo docker compose exec backend alembic upgrade head

# Trader runs as its own service (loads strategies from StrategyConfig DB automatically)
sudo docker compose up -d trader
# หรือรันตรงๆ:
# python trader.py

# Trigger a runtime reload after changing StrategyConfig (no restart needed):
sudo docker compose exec redis redis-cli -a $REDIS_PASSWORD PUBLISH strategy:config_changed ""

# Check paper balance
sudo docker compose exec backend python tasks.py paper-balance

# Celery tasks (cron beat auto-runs data_collector every minute)
sudo docker compose logs -f backend-worker
```

## Architecture

```
BinanceDataFetcher  (WebSocket)
    │  on closed bar
    ▼
StrategyExecuterManager
    │  dispatches Celery task per strategy (Redis lock: 1 concurrent execution per ID)
    ▼
run_strategy task  (Celery worker)
    │
    ├─ StrategyExecuter.execute(tick) → TradeSignal | None
    │
    └─ TradeExecuter → PaperTradeAdapter → Redis (live positions) + Postgres (closed positions)

DataCollector (Celery beat, every 1 min)
    └─ Redis tick buffers → Postgres ticks table
       └─ ProvenQuantDataCollector also POSTs heartbeat to main API
```

## Writing a Custom Strategy

Subclass `StrategyExecuter`:

```python
from app.services.data_fetcher import Subscription, TickData
from app.services.strategy_executer import StrategyExecuter, TradeSignal, SignalSide

class MyStrategy(StrategyExecuter):
    @property
    def id(self) -> str:
        return "my_unique_strategy_id"

    @property
    def subscriptions(self) -> list[Subscription]:
        return [Subscription(asset_slug="btcusdt", timeframe="30m")]

    async def execute(self, tick: TickData) -> TradeSignal | None:
        # your logic here
        ...
```

Save to `backend/strategies/my_strategy.py` and register:

```bash
python tasks.py start-trader --strategy strategies.my_strategy.MyStrategy
```

## Integrating ProvenQuant Signals

Set in `.env`:
```
PROVENQUANT_API_URL=https://api.provenquant.com
PROVENQUANT_API_KEY=your_key
```

Then call `DatasetFetcher.fetch_predictions()` inside your strategy's `execute()`.

## File Map

| Path | Purpose |
|---|---|
| `backend/app/services/trader.py` | Top-level orchestrator |
| `backend/app/services/data_fetcher/__init__.py` | DataFetcher base + TickData |
| `backend/app/services/data_fetcher/binance.py` | Binance WebSocket implementation |
| `backend/app/services/strategy_executer_manager.py` | Dispatch + lock manager |
| `backend/app/services/strategy_executer.py` | StrategyExecuter base + TradeSignal |
| `backend/app/services/trade_executer.py` | Order execution + Postgres position tracking |
| `backend/app/services/trade_adapter/paper.py` | Paper-trade simulation (Redis) |
| `backend/app/services/data_collector/__init__.py` | Redis → Postgres flush (base) |
| `backend/app/services/data_collector/provenquant.py` | + forward heartbeat to main API |
| `backend/app/tasks/strategy.py` | Celery task: run_strategy |
| `backend/app/tasks/data_collector.py` | Celery beat: flush every 1 min |
| `backend/strategies/example_rsi.py` | Example RSI strategy |
