from enum import Enum


class MarketType(str, Enum):
    SPOT = "spot"
    FUTURES = "futures"
    OPTIONS = "options"
