from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from redis import Redis

from trader.app.core import Trader
from trader.logs import get_logger
from trader.util import load_config

app = FastAPI()
redis = Redis()
cfg = load_config()
logger = get_logger()

trader = Trader(redis, cfg)


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
