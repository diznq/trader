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
from redis import Redis

from trader.util import load_config

app = FastAPI()
redis = Redis()
cfg = load_config()

class TraderState(BaseModel):
    stage: str = "buy"

class Trader:
    strategy: BaseStrategy
    trading_strategy: TradingStrategy
    config: Config
    trade_stream: pd.DataFrame
    redis: Redis

    ccy: float = 0
    tgt: float = 0

    def __init__(self, redis: Redis, config: Config, in_data: str = None) -> None:
        pair = config.target + "-" + config.currency
        self.name = "Trader:" + pair.replace("-", ":")
        self.trading_strategy = config.strategy
        self.config = config
        self.strategy = Chad(config.strategy)
        self.redis = redis
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

    def read_state(self) -> str:
        state = self.redis.get(self.name + ":state")
        return state.decode("utf-8") if state is not None else "buy"

    def write_state(self, state: str) -> Optional[bool]:
        return self.redis.set(self.name + ":state", state)

    def read_buy(self, entity="price") -> float:
        value = self.redis.get(self.name + ":buy_" + entity)
        return float(value.decode("utf-8")) if value is not None else None

    def write_buy(self, entity: str, value: float) -> Optional[bool]:
        return self.redis.set(self.name + ":buy_" + entity, str(value))

    def get_account(self, ccy: str):
        return self.client.get_account(self.accountIds[ccy])

    def on_tick(self) -> bool:
        state = self.read_state()
        if self.trade_stream.shape[0] < 2:
            return False

        created_time = pd.Timestamp.utcnow() - pd.DateOffset(minutes=self.trading_strategy.window * 2)
        df = self.trade_stream[self.trade_stream.index > created_time]
        price = df["close"].tail(1)[0]
        roll = df["close"].rolling(str(self.trading_strategy.window)+"min").max().dropna().tail(2).head(1)
        last = roll[0]
        change = price / last - 1

        state = self.read_state()
        print("Last: ", last, ", current: ", price, ", change: ", change)
        if state == "buy" and self.strategy.will_buy(change, price):
            ccy = float(self.get_account(self.config.currency)["available"])
            
            buy_price = price
            much = ccy / price
            much = much / (1 + self.trading_strategy.maker)
            much = math.floor(much * self.config.target_precision) / self.config.target_precision
            
            total_cost = much * price
            fees = total_cost * self.trading_strategy.maker

            if much > 0:
                print("Buying %f %s for %f %s (raw: %f, fees: %f)" % (much, self.config.target, total_cost + fees, self.config.currency, total_cost, fees))
                #self.write_state("buying")
                #self.write_buy("price", buy_price)
                #self.write_buy("amount", much)
            else:
                print("We are broke, man")
        elif state == "buying":
            buy_price = self.read_buy("price")
            much = self.read_buy("amount")
            avail = float(self.get_account(self.config.target)["available"])
            if avail >= much:
                self.write_state("bought")
            # check if it is in our wallet
            pass
        elif state == "bought":
            # sell it?
            pass
        elif state == "selling":
            # check if sold
            pass

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

        self.on_tick()


    def on_shutdown(self):
        self.trade_stream.to_csv(self.out_path)
        self.ws_client.close()

class TraderWSClient(cbpro.WebsocketClient):
    pair: str

    def __init__(self, pair: str, parent: Trader):
        super().__init__()
        self.pair = pair
        self.parent = parent

    def on_open(self):
        self.url = "wss://ws-feed.pro.coinbase.com/"
        self.products = [self.pair]
        self.channels = [
            {
                "name": "ticker",
                "product_ids": [ self.pair ]
            }
        ]
        print("WebSocket client active")

    def on_message(self, msg):
        if "price" in msg and "type" in msg:
            self.parent.on_price(msg)
    
    def on_close(self):
        print("WebSocket client closed")

trader = Trader(redis, cfg, "stok.csv")

@app.get("/")
async def root():
    return json.loads(trader.trade_stream.tail().to_json())

@app.get("/portfolio")
async def portfolio():
    accounts = trader.client.get_accounts()
    holdings = dict()
    whitelist = ["ETH", "EUR"]
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
