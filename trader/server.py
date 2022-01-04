from typing import Optional
from fastapi import FastAPI
from trader.strategy.base import BaseStrategy
from trader.strategy.chad import Chad
from trader.model import TradingStrategy
import pandas as pd
import cbpro

from trader.util import load_config

app = FastAPI()
cfg = load_config()

class Trader:
    strategy: BaseStrategy
    buy_price: Optional[float] = None
    trade_stream: pd.DataFrame

    def __init__(self, pair: str, strategy: TradingStrategy, in_data: str = None) -> None:
        self.strategy = Chad(strategy)
        df = pd.read_csv(in_data, names=["seq", "symbol", "close", "bid", "ask", "side", "time", "txid"], parse_dates=["time"]).set_index("time")
        df = df[df["symbol"] == pair]
        self.trade_stream = df

    def on_price(self, obj):
        new_row = [
            int(obj["sequence"]),
            obj["product_id"],
            float(obj["price"]),
            float(obj["best_bid"]),
            float(obj["best_ask"]),
            obj["side"],
            pd.to_datetime([obj["time"]])[0],
            int(obj["trade_id"])
        ]
        self.trade_stream.append(new_row)

trader = Trader(cfg.pair, cfg.strategy, "stok.csv")

class TraderWSClient(cbpro.WebsocketClient):
    pair: str

    def __init__(self, pair):
        super.__init__()
        self.pair = pair

    def on_open(self):
        self.url = "wss://ws-feed.pro.coinbase.com/"
        self.products = [self.pair]
        self.message_count = 0

    def on_message(self, msg):
        self.message_count += 1
        if 'price' in msg and 'type' in msg:
            print ("Message type:", msg["type"],
                   "\t@ {:.3f}".format(float(msg["price"])))
    
    def on_close(self):
        print("-- Goodbye! --")

wsClient = TraderWSClient()
wsClient.start()

@app.get("/")
async def root():
    return load_config()