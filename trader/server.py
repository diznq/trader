import os

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from redis import Redis

from trader.app.core import Trader
from trader.db.factory import get_db
from trader.logs import get_logger
from trader.strategy.factory import get_strategy
from trader.util import load_config

redis_host = os.environ.get("REDIS_HOST", "localhost")

app = FastAPI()
cfg = load_config()
logger = get_logger()

logger.info(f"Db host: {redis_host}")
db_class = get_db(cfg.db)
db = db_class(host=redis_host)
trading_strategy = get_strategy(cfg.trader, cfg.strategy)
trader = Trader(db, trading_strategy, cfg)


@app.get("/trader/")
async def root():
    return trader.cached_obj("appstatus", 1, lambda: trader.get_status())


@app.get("/trader/portfolio")
async def portfolio():
    return trader.cached_obj("portfolio", 1, lambda: trader.get_portfolio())


@app.get("/trader/equity", response_class=PlainTextResponse)
async def history():
    return trader.get_history().to_csv()


@app.on_event("shutdown")
def shutdown_event():
    trader.on_shutdown()
