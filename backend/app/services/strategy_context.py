from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.services.data_fetcher import TickData
from app.services.fetchers.redis_fetcher import RedisDataFetcher
from app.services.fetchers.db_fetcher import DatabaseDataFetcher
from app.services.fetchers.provenquant_fetcher import ProvenQuantDataFetcher

if TYPE_CHECKING:
    from app.services.strategy_executer import StrategyLeg


@dataclass
class StrategyContext:
    """
    Passed to StrategyExecuter.execute() on every trigger tick.

    Input sources:
      1. tick          — the closed bar that triggered this execution (Input type 1)
      2. redis         — real-time data from WebSocket buffers (Input type 2)
      3. db            — historical OHLCV + market data from Postgres (Input type 3)
      4. pq            — predictions/signals from ProvenQuant platform (Input type 4)
      Input type 5 (Any): strategies may fetch custom data directly inside execute()

    legs: full list of StrategyLegs configured for this strategy.
    leg_num: index of the leg whose tick triggered this execution.
    config_id: DB StrategyConfig.id — used for Redis state key namespacing.
    """

    tick: TickData
    leg_num: int
    legs: list[StrategyLeg]
    config_id: str

    # Fetchers — constructed by the Celery task from config_id
    redis: RedisDataFetcher = field(default_factory=lambda: RedisDataFetcher(""))
    db: DatabaseDataFetcher = field(default_factory=DatabaseDataFetcher)
    pq: ProvenQuantDataFetcher = field(default_factory=ProvenQuantDataFetcher)

    def get_leg(self, leg_num: int) -> StrategyLeg | None:
        """Return the leg with the given index, or None."""
        for leg in self.legs:
            if leg.leg_num == leg_num:
                return leg
        return None

    def get_leg_by_role(self, role: str) -> StrategyLeg | None:
        """Return the first leg matching the given role string, or None."""
        for leg in self.legs:
            if leg.role == role:
                return leg
        return None

    @property
    def trigger_leg(self) -> StrategyLeg | None:
        """The leg that triggered this execution."""
        return self.get_leg(self.leg_num)

    def to_dict(self) -> dict:
        """Serialize to a plain dict for passing through Celery (fetchers are reconstructed)."""
        return {
            "tick": self.tick.to_dict(),
            "leg_num": self.leg_num,
            "legs": [
                {
                    "leg_num": l.leg_num,
                    "role": l.role,
                    "symbol": l.symbol,
                    "exchange": l.exchange,
                    "market_type": l.market_type,
                    "timeframe": l.timeframe,
                    "tick_process": l.tick_process,
                    "subscribe_depth": l.subscribe_depth,
                    "base_asset": l.base_asset,
                    "quote_asset": l.quote_asset,
                    "exchange_account_num": l.exchange_account_num,
                    "transaction_fee": l.transaction_fee,
                    "leverage": l.leverage,
                }
                for l in self.legs
            ],
            "config_id": self.config_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StrategyContext":
        """Reconstruct from Celery-serialized dict (fetchers re-created from config_id)."""
        from app.services.strategy_executer import StrategyLeg
        config_id = data["config_id"]
        legs = [StrategyLeg(**l) for l in data["legs"]]
        return cls(
            tick=TickData(**data["tick"]),
            leg_num=data["leg_num"],
            legs=legs,
            config_id=config_id,
            redis=RedisDataFetcher(config_id),
            db=DatabaseDataFetcher(),
            pq=ProvenQuantDataFetcher(),
        )
