import asyncio
import logging

from app.services.trade_executer_process import TradeExecuterProcess

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    asyncio.run(TradeExecuterProcess().start())
