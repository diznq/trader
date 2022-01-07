import json
import logging
import math
import os
import time
from types import LambdaType
from typing import Optional

import cbpro
import pandas as pd
from fastapi import FastAPI
from pydantic.main import BaseModel
from redis import Redis

from trader.model import Config, TradingStrategy
from trader.strategy.base import BaseStrategy
from trader.strategy.chad import Chad
from trader.util import load_config

logger = logging.getLogger("server")
logger.setLevel(logging.INFO)

formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
fh = logging.FileHandler("logs/trades.log")
fh.setLevel(logging.INFO)
fh.setFormatter(formatter)
logger.addHandler(fh)

app = FastAPI()
redis = Redis()
cfg = load_config()


class TraderState(BaseModel):
    stage: str = "buy"


class Trader:
    redis: Redis
    strategy: BaseStrategy

    config: Config
    trading_strategy: TradingStrategy

    trade_stream: pd.DataFrame
    pair: str
    ccy: float = 0
    tgt: float = 0
    tick_period: float = 0.25

    last_change: float = 0
    current_price: float = 0
    current_max: float = 0

    def __init__(self, redis: Redis, config: Config, in_data: str = None) -> None:
        pair = config.target + "-" + config.currency
        self.pair = pair
        self.tick_period = 1.0 / config.tick_rate
        self.period = self.tick_period
        self.name = "Trader:" + pair.replace("-", ":")
        self.trading_strategy = config.strategy
        self.config = config
        self.strategy = Chad(config.strategy)
        self.redis = redis
        self.active = True
        self.last_tick = time.perf_counter()
        self.out_path = "data/" + config.target + "_" + config.currency + ".csv"

        if not os.path.exists(self.out_path):
            df = pd.read_csv(
                in_data,
                header=None,
                names=["seq", "symbol", "close", "bid", "ask", "side", "time", "txid"],
                parse_dates=["time"],
            ).set_index("time")
            df = df[df["symbol"] == pair]
            df.to_csv(self.out_path)

        # Prepare dynamic stuff
        apikey = self.config.apikey
        df = pd.read_csv(self.out_path, parse_dates=["time"]).set_index("time")
        df = df[df["symbol"] == pair]
        self.trade_stream = df
        if config.sandbox:
            apikey = self.config.sandbox_apikey
            self.client = cbpro.AuthenticatedClient(
                apikey.name,
                apikey.key,
                apikey.passphrase,
                api_url="https://api-public.sandbox.exchange.coinbase.com",
            )
        else:
            self.client = cbpro.AuthenticatedClient(apikey.name, apikey.key, apikey.passphrase)

        # Let's cache points of our interest
        whitelist = [config.target, config.currency]
        self.accountIds = dict()
        accounts = self.client.get_accounts()
        for account in accounts:
            if account["currency"] in whitelist:
                self.accountIds[account["currency"]] = account["id"]
            if account["currency"] == config.currency:
                self.ccy = float(account["available"])
            elif account["currency"] == config.target:
                self.tgt = float(account["available"])

        self.start_ws_client()

        logger.info("Trader active, currency: %f, crypto: %f" % (self.ccy, self.tgt))

    def read(self, entity) -> str:
        value = self.redis.get(self.name + ":" + entity)
        return value.decode("utf-8") if value is not None else None

    def write(self, entity, value, ex: int=None) -> Optional[bool]:
        if ex is None:
            return self.redis.set(self.name + ":" + entity, value)
        return self.redis.setex(self.name + ":" + entity, ex, value)

    def cached(self, entity, ex: int, getter: LambdaType) -> Optional[str]:
        key = self.name + ":" + entity
        value = self.redis.get(key)
        if value is None:
            value = getter()
            self.redis.setex(key, ex, value)
        return value

    def cached_obj(self, entity, ex: int, getter: LambdaType) -> Optional[str]:
        return json.loads(self.cached(entity, ex, lambda: json.dumps(getter())))

    def read_state(self) -> str:
        state = self.read("state")
        return state if state is not None else "buy"

    def write_state(self, state: str) -> Optional[bool]:
        return self.write("state", state)

    def read_num(self, entity="buy_price") -> Optional[float]:
        value = self.read(entity)
        return float(value) if value is not None else None

    def write_num(self, entity: str, value: float) -> Optional[bool]:
        return self.write(entity, str(value))

    def get_account(self, ccy: str):
        return self.client.get_account(self.accountIds[ccy])

    def get_xchg_rate(self) -> Optional[float]:
        return self.read_num("xchg")

    def tick(self):
        t = time.perf_counter()
        if t - self.last_tick >= self.period:
            self.on_tick()
            self.last_tick = t

    def on_tick(self) -> bool:
        state = self.read_state()
        if self.trade_stream.shape[0] < 2:
            return True

        # Get rid of old stuff
        created_time = pd.Timestamp.utcnow() - pd.DateOffset(minutes=self.trading_strategy.window * 2)
        self.trade_stream = self.trade_stream[self.trade_stream.index > created_time]

        # Create a copy that we work with from now on
        df = self.trade_stream.copy()
        # Get current price
        price = df["close"].tail(1)[0]
        # Get previous max over time window
        last = df["close"].rolling(str(self.trading_strategy.window) + "min").max().dropna().tail(2).head(1)[0]
        # Calculate change
        change = price / last - 1

        self.current_price = price
        self.current_max = last
        self.last_change = change

        state = self.read_state()
        # logger.info( "%s | %s | Max: %f, now: %f, chg: %f" % (self.pair, state, last, price, change) )
        if state == "buy":
            self.period = self.tick_period
            buy_price = price

            if self.config.place_immediately:
                buy_price = self.strategy.buy_price(change, last, price)
            elif not self.strategy.will_buy(change, price):
                return True

            if buy_price is None:
                return True

            trigger_price = buy_price
            buy_price = buy_price * (1.0 - self.trading_strategy.buy_underprice)

            # Let's determine how much we have and how much we can afford to buy
            ccy = float(self.get_account(self.config.currency)["available"]) * self.config.trade_partition

            # Align buy price to tick size of currency and calculate maximum we can buy with that
            buy_price = math.floor(buy_price * self.config.currency_precision) / self.config.currency_precision
            much = ccy / buy_price

            # As we are trying to buy as quick as possible, we are considered takers
            much = much / (1 + self.trading_strategy.taker)

            # Make sure we use exact tick size for amount
            much = math.floor(much * self.config.target_precision) / self.config.target_precision

            # Estimate cost
            total_cost = much * buy_price
            fees = total_cost * self.trading_strategy.taker

            if much > 0:
                logger.info(
                    "Buying %f %s for %f %s (xchg rate: %f, raw: %f, fees: %f)"
                    % (
                        much,
                        self.config.target,
                        total_cost + fees,
                        self.config.currency,
                        buy_price,
                        total_cost,
                        fees,
                    )
                )
                # Overwrite state first, so it can't happen that due to laggy internet connection
                # this state-branch would get called once again and try to buy twice :D
                self.write_state("buying")
                self.write_num("buy_trigger_price", trigger_price)
                self.write_num("buy_price", buy_price)
                self.write_num("buy_amount", much)
                self.write_num("buy_cost", total_cost + fees)
                self.write_num("buy_fees", fees)
                self.write_num("buy_value", total_cost)

                # Place an order and save response
                resp = self.client.place_limit_order(
                    product_id=self.pair,
                    side="buy",
                    price=str(buy_price),
                    size=str(much),
                )
                self.write("buy_response", json.dumps(resp))

                if "message" in resp:
                    # If it fails, return to current state and try once again
                    logger.error("Buying failed, reason: %s" % (resp["message"]))
                    self.write_state("buy")
        elif state == "buying":
            self.period = self.tick_period * 4
            much = self.read_num("buy_amount")
            order = json.loads(self.read("buy_response"))
            status = self.client.get_order(order["id"])
            if "message" in status:
                logger.warning("Buy order was cancelled, reverting to buy stage")
                self.write_state("buy")
            elif status["status"] == "done":
                logger.info("Successfuly bought %s, balance: %f %s" % (self.config.target, much, self.config.target))
                self.write_state("bought")
        elif state == "bought":
            self.period = self.tick_period * 4
            buy_price = self.read_num("buy_price")
            sell_price = self.strategy.sell_price(change, buy_price / (1.0 - self.trading_strategy.buy_underprice), price)
            if sell_price is None:
                return True

            # Make sure sell price is aligned to tick size of target asset
            sell_price = math.ceil(sell_price * self.config.currency_precision) / self.config.currency_precision

            # Calculate how much coin we have and how much we'll probably earn, we are maker now
            # as we don't expect sell to happen immediately
            avail = float(self.get_account(self.config.target)["available"])
            total_earn = avail * sell_price
            fees = total_earn * self.trading_strategy.maker

            logger.info(
                "Selling %f %s for %f %s (xchg: %f, raw: %f, fees: %f)"
                % (
                    avail,
                    self.config.target,
                    total_earn - fees,
                    self.config.currency,
                    sell_price,
                    total_earn,
                    fees,
                )
            )

            # Make sure we overwrite state even before we place order
            # so we can't place it twice :D
            self.write_state("selling")
            self.write_num("sell_price", sell_price)
            self.write_num("sell_amount", avail)
            self.write_num("sell_value", total_earn - fees)
            self.write_num("sell_fees", fees)
            self.write_num("sell_revenue", total_earn)

            # Place an order and save response
            resp = self.client.place_limit_order(
                product_id=self.pair,
                side="sell",
                price=str(sell_price),
                size=str(avail),
            )
            self.write("sell_response", json.dumps(resp))

            # Check if the order was successful (it contains message with error if not)
            if "message" in resp:
                logger.info("Selling failed, reason: %s" % (resp["message"]))
                self.write_state("bought")

        elif state == "selling":
            self.period = self.tick_period * 4
            much = self.read_num("sell_amount")
            order = json.loads(self.read("sell_response"))
            status = self.client.get_order(order["id"])
            if "message" in status:
                logger.warning("Sell order was cancelled, reverting to bought stage")
                self.write_state("bought")
            elif status["status"] == "done":
                logger.info("Successfuly sold %s, balance: %f %s" % (self.config.target, much, self.config.target))
                self.write_state("buy")

        return True

    def on_price(self, obj):
        new_row = {
            "seq": int(obj["sequence"]),
            "symbol": obj["product_id"],
            "close": float(obj["price"]),
            "bid": float(obj["best_bid"]),
            "ask": float(obj["best_ask"]),
            "side": obj["side"],
            "txid": int(obj["trade_id"]),
        }
        time = pd.to_datetime([obj["time"]])[0]
        self.write_num("xchg", new_row["close"])
        self.trade_stream.loc[time] = new_row
        self.tick()

    def start_ws_client(self):
        self.ws_client = TraderWSClient(self.pair, self, self.config.sandbox)
        self.ws_client.start()

    def on_ws_dead(self):
        if self.active:
            logger.warning("Websocket client closed, reconnecting")
            time.sleep(1)
            self.start_ws_client()
        else:
            logger.info("Websocket client closed")

    def on_shutdown(self):
        logger.info("Shutting down")
        self.active = False
        self.trade_stream.to_csv(self.out_path)
        self.ws_client.close()

    def get_accounts(self):
        return self.cached_obj("accounts", 5, lambda: self.client.get_accounts())

    def get_status(self):
        return self.cached_obj("appstatus", 1, lambda: {
            "max": self.current_max,
            "current": self.current_price,
            "change": self.last_change,
            "state": self.read_state(),
            "buy": {
                "price": self.read_num("buy_price"),
                "trigger": self.read_num("buy_trigger_price"),
                "amount": self.read_num("buy_amount"),
                "value": self.read("buy_value"),
                "cost": self.read("buy_cost"),
                "fees": self.read("buy_fees")
            },
            "sell": {
                "price": self.read_num("sell_price"),
                "amount": self.read_num("sell_amount"),
                "value": self.read("sell_value"),
                "revenue": self.read("sell_revenue"),
                "fees": self.read("sell_fees")
            }
        })


class TraderWSClient(cbpro.WebsocketClient):
    pair: str

    def __init__(self, pair: str, parent: Trader, sandbox: bool = False):
        super().__init__()
        self.pair = pair
        self.parent = parent
        self.sandbox = sandbox

    def on_open(self):
        self.url = "wss://ws-feed.pro.coinbase.com/"
        if self.sandbox:
            self.url = "wss://ws-feed-public.sandbox.exchange.coinbase.com/"
        print(self.url)
        self.products = [self.pair]
        self.channels = [{"name": "ticker", "product_ids": [self.pair]}]
        logger.info("Websocket client opened")

    def on_message(self, msg):
        if "price" in msg and "type" in msg:
            self.parent.on_price(msg)

    def on_close(self):
        self.parent.on_ws_dead()


trader = Trader(redis, cfg, "stock_dataset.csv")


@app.get("/trader/")
async def root():
    return trader.get_status()


@app.get("/trader/portfolio")
async def portfolio():
    accounts = trader.get_accounts()
    holdings = dict()
    equity = 0
    whitelist = [cfg.target, cfg.currency]
    for account in accounts:
        if account["currency"] in whitelist:
            if account["currency"] == cfg.currency:
                equity += float(account["available"])
            elif account["currency"] == cfg.target:
                equity += float(account["available"]) * trader.get_xchg_rate()
            holdings[account["currency"]] = {
                "balance": account["balance"],
                "hold": account["hold"],
                "available": account["available"],
            }
    return {"equity": equity, "holdings": holdings}


@app.on_event("shutdown")
def shutdown_event():
    trader.on_shutdown()
