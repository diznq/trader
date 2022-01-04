from typing import Optional
from fastapi import FastAPI
from pydantic.main import BaseModel
from trader.strategy.base import BaseStrategy
from trader.strategy.chad import Chad
from trader.model import Config, TradingStrategy
import pandas as pd
import cbpro
import json
import math
import os
import time
import logging
from redis import Redis

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

    def __init__(self, redis: Redis, config: Config, in_data: str = None) -> None:
        pair = config.target + "-" + config.currency
        self.pair = pair
        self.name = "Trader:" + pair.replace("-", ":")
        self.trading_strategy = config.strategy
        self.config = config
        self.strategy = Chad(config.strategy)
        self.redis = redis
        self.active = True
        self.last_tick = time.perf_counter()
        self.out_path = "data/" + config.target + "_" + config.currency + ".csv"

        if not os.path.exists(self.out_path):
            df = pd.read_csv(in_data, header=None, names=["seq", "symbol", "close", "bid", "ask", "side", "time", "txid"], parse_dates=["time"]).set_index("time")
            df = df[df["symbol"] == pair]
            df.to_csv(self.out_path)

        # Prepare dynamic stuff
        apikey = self.config.apikey
        df = pd.read_csv(self.out_path, parse_dates=["time"]).set_index("time")
        df = df[df["symbol"] == pair]
        self.trade_stream = df
        if config.sandbox:
            apikey = self.config.sandbox_apikey
            self.client = cbpro.AuthenticatedClient(apikey.name, apikey.key, apikey.passphrase, api_url="https://api-public.sandbox.exchange.coinbase.com")
        else:
            self.client = cbpro.AuthenticatedClient(apikey.name, apikey.key, apikey.passphrase)
        self.ws_client = TraderWSClient(pair, self)
        self.ws_client.start()

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

        logger.info("Trader active, currency: %f, crypto: %f" % (self.ccy, self.tgt))

    def read(self, entity) -> str:
        value = self.redis.get(self.name + ":" + entity)
        return value.decode("utf-8") if value is not None else None

    def write(self, entity, value) -> Optional[bool]:
        return self.redis.set(self.name + ":" + entity, value)

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

    def tick(self):
        t = time.perf_counter()
        if t - self.last_tick >= 0.25:
            self.on_tick()
            self.last_tick = t

    def on_tick(self) -> bool:
        state = self.read_state()
        if self.trade_stream.shape[0] < 2:
            return False

        # Get rid of old stuff
        created_time = pd.Timestamp.utcnow() - pd.DateOffset(minutes=self.trading_strategy.window * 2)
        self.trade_stream = self.trade_stream[self.trade_stream.index > created_time]

        # Create a copy that we work with from now on
        df = self.trade_stream.copy()
        # Get current price
        price = df["close"].tail(1)[0]
        # Get previous max over time window
        last = df["close"].rolling(str(self.trading_strategy.window)+"min").max().dropna().tail(2).head(1)[0]
        # Calculate change
        change = price / last - 1

        state = self.read_state()
        logger.info("%s | %s | Max: %f, now: %f, chg: %f" % (self.pair, state, last, price, change))
        if state == "buy" and self.strategy.will_buy(change, price):
            # Let's determine how much we have and how much we can afford to buy
            ccy = float(self.get_account(self.config.currency)["available"])

            # Align buy price to tick size of currency and calculate maximum we can buy with that
            buy_price = math.floor(price * self.config.currency_precision) / self.config.currency_precision
            much = ccy / buy_price

            # As we are trying to buy as quick as possible, we are considered takers
            much = much / (1 + self.trading_strategy.taker)

            # Make sure we use exact tick size for amount
            much = math.floor(much * self.config.target_precision) / self.config.target_precision
            
            # Estimate cost
            total_cost = much * buy_price
            fees = total_cost * self.trading_strategy.taker

            if much > 0:
                logger.info("Buying %f %s for %f %s (xchg rate: %f, raw: %f, fees: %f)" % (much, self.config.target, total_cost + fees, self.config.currency, buy_price, total_cost, fees))
                # Overwrite state first, so it can't happen that due to laggy internet connection
                # this state-branch would get called once again and try to buy twice :D
                self.write_state("buying")
                self.write_num("buy_price", buy_price)
                self.write_num("buy_amount", much)
                
                # Place an order and save response
                resp = self.client.place_limit_order(
                    product_id=self.pair, 
                    side="buy",
                    price=str(buy_price), 
                    size=str(much)
                )
                self.write("buy_response", json.dumps(resp))

                if "message" in resp:
                    # If it fails, return to current state and try once again
                    logger.error("Buying failed, reason: %s" % (resp["message"]))
                    self.write_state("buy")
        elif state == "buying":
            much = self.read_num("buy_amount")
            avail = float(self.get_account(self.config.target)["available"])
            if avail >= much:
                logger.info("Successfuly bought %s, balance: %f %s" % (self.config.target, avail, self.config.target))
                self.write_state("bought")
        elif state == "bought":
            buy_price = self.read_num("buy_price")
            sell_price = self.strategy.sell_price(change, buy_price, price)
            if sell_price is None:
                return True

            # Make sure sell price is aligned to tick size of target asset
            sell_price = math.ceil(sell_price * self.config.currency_precision) / self.config.currency_precision

            # Calculate how much coin we have and how much we'll probably earn, we are maker now
            # as we don't expect sell to happen immediately
            avail = float(self.get_account(self.config.target)["available"])
            total_earn = avail * sell_price
            fees = total_earn * self.trading_strategy.maker

            logger.info("Selling %f %s for %f %s (xchg: %f, raw: %f, fees: %f)" % (avail, self.config.target, total_earn - fees, self.config.currency, sell_price, total_earn, fees))
            
            # Make sure we overwrite state even before we place order
            # so we can't place it twice :D
            self.write_state("selling")
            self.write_num("sell_price", sell_price)
            self.write_num("sell_amount", total_earn - fees)

            # Place an order and save response
            resp = self.client.place_limit_order(
                product_id=self.pair, 
                side="sell",
                price=str(sell_price), 
                size=str(avail)
            )
            self.write("sell_response", json.dumps(resp))

            # Check if the order was successful (it contains message with error if not)
            if "message" in resp:
                logger.info("Selling failed, reason: %s" % (resp["message"]))
                self.write_state("bought")

        elif state == "selling":
            much = self.read_num("sell_amount")
            avail = float(self.get_account(self.config.currency)["available"])
            if avail >= much:
                logger.info("Successfuly sold %s, balance now: %f %s" % (self.config.target, avail, self.config.currency))
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
            "txid": int(obj["trade_id"])
        }
        time = pd.to_datetime([obj["time"]])[0]
        self.trade_stream.loc[time] = new_row
        self.tick()


    def on_shutdown(self):
        logger.info("Shutting down")
        self.active = False
        self.trade_stream.to_csv(self.out_path)
        self.ws_client.close()

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
        self.products = [self.pair]
        self.channels = [
            {
                "name": "ticker",
                "product_ids": [ self.pair ]
            }
        ]

    def on_message(self, msg):
        if "price" in msg and "type" in msg:
            self.parent.on_price(msg)
    
    def on_close(self):
        pass

trader = Trader(redis, cfg, "stok.csv")

@app.get("/")
async def root():
    return json.loads(trader.trade_stream.tail().to_json())

@app.get("/portfolio")
async def portfolio():
    accounts = trader.client.get_accounts()
    holdings = dict()
    whitelist = [cfg.target, cfg.currency]
    for account in accounts:
        if account["currency"] in whitelist:
            holdings[account["currency"]] = {
                "balance": account["balance"],
                "hold": account["hold"],
                "available": account["available"]
            }
    return holdings

@app.on_event('shutdown')
def shutdown_event():
    trader.on_shutdown()
