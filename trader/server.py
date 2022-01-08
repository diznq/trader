from fastapi import FastAPI
from redis import Redis

from trader.app.core import Trader
from trader.logs import get_logger
from trader.util import load_config

app = FastAPI()
redis = Redis()
cfg = load_config()
logger = get_logger()

trader = Trader(redis, cfg, "stock_dataset.csv")


@app.get("/trader/")
async def root():
    return trader.get_status()


@app.get("/trader/portfolio")
async def portfolio():
    accounts = trader.get_accounts()
    holdings = dict()
    equity = 0
    avail_equity = 0
    whitelist = [cfg.target, cfg.currency]
    for account in accounts:
        if account["currency"] in whitelist:
            if account["currency"] == cfg.currency:
                equity += float(account["balance"])
                avail_equity += float(account["available"])
            elif account["currency"] == cfg.target:
                xchg = trader.get_xchg_rate()
                equity += float(account["balance"]) * xchg
                avail_equity += float(account["available"]) * xchg
            holdings[account["currency"]] = {
                "balance": account["balance"],
                "hold": account["hold"],
                "available": account["available"],
            }
    return {"equity": {"balance": equity, "available": avail_equity}, "holdings": holdings}


@app.on_event("shutdown")
def shutdown_event():
    trader.on_shutdown()
