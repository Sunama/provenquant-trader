import asyncio
from app.services.trader import Trader

if __name__ == "__main__":
    asyncio.run(Trader().start())
