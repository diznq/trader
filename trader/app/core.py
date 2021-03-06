import json
import math
import os
import time
from threading import Lock
from types import LambdaType
from typing import Dict, Optional

import cbpro
import pandas as pd
from redis import Redis

from trader.logs import get_logger
from trader.model import Config, TradingStrategy
from trader.strategy.base import BaseStrategy

logger = get_logger()


class Trader:
    redis: Redis
    strategy: BaseStrategy

    config: Config
    trading_strategy: TradingStrategy

    trade_stream: pd.DataFrame
    equity_stream: pd.DataFrame
    pair: str
    tick_period: float = 0.25

    last_change: float = 0
    current_price: float = 0
    current_max: float = 0
    current_min: float = 0
    current_round: int = 0
    current_temperature: float = 0
    lock = Lock()

    def __init__(self, redis: Redis, trading_strategy: BaseStrategy, config: Config) -> None:
        pair = config.target + "-" + config.currency
        in_data = config.initial_dataset
        self.pair = pair
        self.tick_period = 1.0 / config.tick_rate
        self.period = self.tick_period
        self.name = "Trader:" + pair.replace("-", ":")
        self.trading_strategy = config.strategy
        self.config = config
        self.strategy = trading_strategy
        self.redis = redis
        self.active = True
        self.last_tick = time.perf_counter()
        self.out_path = "data/" + config.target + "_" + config.currency + ".csv"

        logger.info(f"Initial dataset located at {in_data}")

        if not os.path.exists(self.out_path):
            df = None
            logger.info("Loading initial dataset")
            if os.path.exists(in_data):
                df = pd.read_csv(
                    in_data,
                    header=None,
                    names=["seq", "symbol", "close", "bid", "ask", "side", "time", "txid"],
                    parse_dates=["time"],
                ).set_index("time")
            else:
                logger.warn(f"Input data path {in_data} doesn't exist, creating empty dataset instead")
                df = pd.DataFrame(
                    columns=["seq", "symbol", "close", "bid", "ask", "side", "txid"],
                    index=pd.to_datetime([], utc=True),
                )
                df.index.name = "time"
            df = df[df["symbol"] == pair]
            df.to_csv(self.out_path)
            logger.info("Initial dataset loaded")

        # Prepare dynamic stuff
        apikey = self.config.apikey
        logger.info("Loading cached dataframe")
        df = pd.read_csv(self.out_path, parse_dates=["time"]).set_index("time")
        df = df[df["symbol"] == pair]
        if "vol" not in df.columns:
            df["vol"] = 0
        self.trade_stream = df
        logger.info("Creating Coinbase client")
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
        logger.info("Loading account details")
        whitelist = [config.target, config.currency]
        self.accountIds = dict()
        accounts = self.client.get_accounts()
        for account in accounts:
            if account["currency"] in whitelist:
                self.accountIds[account["currency"]] = account["id"]
            if account["currency"] in [config.currency, config.target]:
                self.write_num(account["currency"], float(account["balance"]))

        logger.info("Loading cached equity stream")
        self.equity_stream = pd.DataFrame(columns=["equity", "ccy", "crypto"], index=pd.to_datetime([], utc=True))
        self.equity_stream.index.name = "time"
        if os.path.exists("data/equity_stream.csv"):
            self.equity_stream = pd.read_csv("data/equity_stream.csv", parse_dates=["time"]).set_index("time")

        logger.info("Loading balanced")
        balances = self.get_balances(False)
        self.start_ws_client()

        logger.info("Trader active, currency: %f, crypto: %f" % (balances[config.currency], balances[config.target]))

    def read(self, entity) -> str:
        value = self.redis.get(self.name + ":" + entity)
        return value.decode("utf-8") if value is not None else None

    def write(self, entity, value, ex: int = None) -> Optional[bool]:
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

    def update_balances(self) -> Dict[str, float]:
        dct = dict()
        for ccy in [self.config.currency, self.config.target]:
            acc = self.get_account(ccy)
            dct[ccy] = float(acc["balance"])
            self.write_num(ccy, float(acc["balance"]))
        return dct

    def get_balances(self, cached=True) -> Dict[str, float]:
        if not cached:
            return self.update_balances()
        dct = dict()
        for ccy in [self.config.currency, self.config.target]:
            dct[ccy] = self.read_num(ccy)
        return dct

    def calc_equity(self, balances: Dict[str, float]) -> float:
        xchg = {self.config.currency: 1, self.config.target: self.get_xchg_rate()}
        sum = 0
        for key in balances:
            if key not in xchg:
                continue
            sum += xchg[key] * balances[key]
        return sum

    def tick(self, time_index):
        with self.lock:
            t = time.perf_counter()
            if t - self.last_tick >= self.period:
                try:
                    self.on_tick(time_index)
                except Exception as ex:
                    logger.error("Tick failed with exception", exc_info=ex)
                self.last_tick = t

    def on_tick(self, time_index) -> bool:
        state = self.read_state()
        if self.trade_stream.shape[0] < 2:
            return True

        # Log our current equity
        balances = self.get_balances()
        equity = self.calc_equity(balances)
        self.equity_stream.loc[time_index] = {
            "equity": equity,
            "ccy": balances[self.config.currency],
            "crypto": balances[self.config.target],
        }

        # Get rid of old stuff
        req_window = max(self.config.temperature.window, self.trading_strategy.window)
        created_time = pd.Timestamp.utcnow() - pd.DateOffset(minutes=req_window * 2)
        self.trade_stream = self.trade_stream[self.trade_stream.index > created_time]

        # Create a copy that we work with from now on
        df = self.trade_stream.copy()
        # Get current price
        price = df["close"].tail(1)[0]
        # Get previous min/max over time window

        frame = df["close"].rolling(str(self.trading_strategy.window) + "min").max().dropna()
        if frame.shape[0] == 0:
            return True

        last = df["close"].rolling(str(self.trading_strategy.window) + "min").max().dropna().tail(2).head(1)[0]
        last_min = df["close"].rolling(str(self.trading_strategy.window) + "min").min().dropna().tail(2).head(1)[0]
        # Calculate change
        change = price / last - 1

        # Calculate temperature
        temp_min = df["close"].rolling(str(self.config.temperature.window) + "min").min().tail(1)[0]
        temp_max = df["close"].rolling(str(self.config.temperature.window) + "min").max().tail(1)[0]
        temperature = temp_max / temp_min - 1

        self.current_temperature = temperature
        self.current_price = price
        self.current_max = last
        self.current_min = last_min
        self.last_change = change

        state = self.read_state()
        round = self.read_num("round")
        if round is None:
            round = 0
        round = int(round)
        self.current_round = round
        # logger.info( "%s | %s | Max: %f, now: %f, chg: %f" % (self.pair, state, last, price, change) )
        if state == "buy":
            # In this stage we haven't bought anything yet and we are looking to buy something
            self.period = self.tick_period
            buy_price = price

            # Prevent trading when temperature is out of band
            outside_band = temperature >= self.config.temperature.max or temperature <= self.config.temperature.min
            if self.config.temperature.enabled and outside_band:
                return True

            if self.config.place_immediately:
                buy_price = self.strategy.buy_price(self)
            elif not self.strategy.will_buy(self):
                return True

            if buy_price is None:
                return True

            trigger_price = buy_price
            buy_price = buy_price * (1.0 - self.trading_strategy.buy_underprice)

            # Let's determine how much we have and how much we can afford to buy
            ccy = float(self.get_account(self.config.currency)["available"]) * self.config.trade_partition

            fee_ratio = self.get_flat_fee()

            # Align buy price to tick size of currency and calculate maximum we can buy with that
            buy_price = math.floor(buy_price * self.config.currency_precision) / self.config.currency_precision
            much = ccy / buy_price

            # As we are trying to buy as quick as possible, we are considered takers
            much = much / (1 + fee_ratio)

            # Make sure we use exact tick size for amount
            much = math.floor(much * self.config.target_precision) / self.config.target_precision

            # Estimate cost
            total_cost = much * buy_price
            fees = total_cost * fee_ratio

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
                self.write_num("buy_trigger_max", last)
                self.write_num("buy_trigger_price", trigger_price)
                self.write_num("buy_price", buy_price)
                self.write_num("buy_amount", much)
                self.write_num("buy_cost", total_cost + fees)
                self.write_num("buy_fees", fees)
                self.write_num("buy_value", total_cost)
                self.write_num("buy_time", time.time())

                # Place an order and save response
                resp = self.client.place_limit_order(
                    product_id=self.pair,
                    side="buy",
                    post_only=True,
                    price=str(buy_price),
                    size=str(much),
                )
                self.write("buy_response", json.dumps(resp))

                if "message" in resp:
                    # If it fails, return to current state and try once again
                    logger.error("Buying failed, reason: %s" % (resp["message"]))
                    self.write_state("buy")
        elif state == "buying":
            # In this stage we already place a limit buy order and are waiting for it's completion
            # if the buy order was cancelled (by user in UI), we go back to buy stage
            self.period = self.tick_period * 4
            order = json.loads(self.read("buy_response"))
            status = self.client.get_order(order["id"])
            trigger_max = self.read_num("buy_trigger_max")
            buy_time = self.read_num("buy_time")            

            if "message" in status and status["message"] == "NotFound":
                if (time.time() - buy_time) < 60:
                    return False
                logger.warning("Buy order was cancelled, reverting to buy stage")
                logger.warning(status)
                self.write_state("buy")
            elif (
                status["status"] == "open"
                and self.config.place_immediately
                and float(status["filled_size"]) <= 0
                and trigger_max != last
            ):
                # Cancel order if place immediately is active and rolling maximum changed
                logger.warning(f"Cancelling buy order, as it rolling max changed from {trigger_max} to {last}")
                self.client.cancel_order(order["id"])
                self.write_state("buy")
            elif status["status"] == "open" and self.config.autocancel > 0 and float(status["filled_size"]) <= 0:
                # Cancel order if buying timed out
                if (time.time() - buy_time) >= (self.config.autocancel * 60):
                    logger.warning("Cancelling buy order, as it took much longer than expected")
                    self.client.cancel_order(order["id"])
                    self.write_state("buy")
            elif status["status"] == "done":
                # Make sure it's written very first, so even if get_account fails, we are safe
                self.write_state("bought")
                balances = self.get_balances(False)
                much = balances[self.config.target]
                logger.info("Successfuly bought %s, balance: %f %s" % (self.config.target, much, self.config.target))
        elif state == "bought":
            # In this stage we successfuly obtained new crypto currency and we try to sell it by placing
            # a new limit sell order, accounting for buy/sell fees
            self.period = self.tick_period * 4
            buy_price = self.read_num("buy_price")
            buy_fees = self.read_num("buy_fees")
            if buy_price is None:
                return True
            sell_price = self.strategy.sell_price(self)

            # Calculate how much coin we have and how much we'll probably earn, we are maker now
            # as we don't expect sell to happen immediately
            avail = float(self.get_account(self.config.target)["available"])

            fee_ratio = self.get_flat_fee()

            avail = math.floor(avail * self.config.target_precision) / self.config.target_precision

            if avail <= 0:
                return True

            net_sell_price = sell_price
            # compensate buyer fee
            sell_price = (sell_price * avail + buy_fees) / avail
            # compensate seller fee
            sell_price = sell_price / (1 - fee_ratio)

            # Make sure sell price is aligned to tick size of target asset
            sell_price = math.ceil(sell_price * self.config.currency_precision) / self.config.currency_precision

            total_earn = avail * sell_price
            fees = total_earn * fee_ratio

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
            self.write_num("sell_time", time.time())
            self.write_num("margin", sell_price / buy_price)
            self.write_num("net_sell_price", net_sell_price)
            self.write_num("net_margin", net_sell_price / buy_price)

            # Place an order and save response
            resp = self.client.place_limit_order(
                product_id=self.pair,
                side="sell",
                post_only=True,
                price=str(sell_price),
                size=str(avail),
            )
            self.write("sell_response", json.dumps(resp))

            # Check if the order was successful (it contains message with error if not)
            if "message" in resp:
                logger.info("Selling failed, reason: %s" % (resp["message"]))
                self.write_state("bought")

        elif state == "selling":
            # In this stage we are waiting for completion of limit sell order,
            # if the order was cancelled, we revert back to sell stage, otherwise
            # if the order was completed, we go back to buy stage
            self.period = self.tick_period * 4
            order = json.loads(self.read("sell_response"))
            status = self.client.get_order(order["id"])
            sell_time = self.read_num("sell_time")
                
            if "message" in status and status["message"] == "NotFound":
                if (time.time() - sell_time) < 60:
                    return False
                logger.warning("Sell order was cancelled, reverting to bought stage")
                logger.warning(status)
                self.write_state("bought")
            elif status["status"] == "done":
                self.write_state("buy")
                self.write_num("round", round + 1)
                balances = self.get_balances(False)
                much = balances[self.config.currency]
                logger.info("Successfuly sold %s, balance: %f %s" % (self.config.target, much, self.config.currency))

        return True

    def on_price(self, obj):
        new_row = {
            "seq": int(obj["sequence"]),
            "symbol": obj["product_id"],
            "close": float(obj["price"]),
            "bid": float(obj["best_bid"]),
            "ask": float(obj["best_ask"]),
            "side": obj["side"],
            "vol": float(obj["last_size"]),
            "txid": int(obj["trade_id"]),
        }
        time_index = pd.to_datetime([obj["time"]])[0]
        self.write_num("xchg", new_row["close"])
        self.trade_stream.loc[time_index] = new_row
        # Make sure we go through tick fn, so we don't update every now and then
        # but rather in predefined intervals. In this fashion, we don't get hit by
        # rate limiter
        self.tick(time_index)

    def get_cashflow(self):
        df = self.trade_stream.copy()
        df["cash"] = df["close"] * df["vol"]
        sellers = df[df["side"] == "sell"]
        buyers = df[df["side"] == "buy"]
        sell_sum = sellers["cash"].sum()
        buy_sum = buyers["cash"].sum()
        return {"buyers": buy_sum, "sellers": sell_sum, "cashflow": sell_sum - buy_sum}

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
        self.equity_stream.to_csv("data/equity_stream.csv")
        self.ws_client.close()

    def get_fees(self):
        return self.client._send_message("get", "/fees")

    def get_accounts(self):
        return self.cached_obj("accounts", 5, lambda: self.client.get_accounts())

    def get_history(self) -> pd.DataFrame:
        return self.equity_stream

    def get_flat_fee(self):
        if self.config.forex:
            return 0
        fees = self.cached_obj("fees", 5, lambda: self.get_fees())
        maker = float(fees["maker_fee_rate"])
        taker = float(fees["taker_fee_rate"])
        fee_ratio = min(maker, taker)
        return fee_ratio

    def get_status(self):
        fee_ratio = self.get_flat_fee()
        round = self.read_num("round")
        if round is None:
            round = 0
        round = int(round)
        temperature = self.current_temperature
        outside_band = temperature >= self.config.temperature.max or temperature <= self.config.temperature.min
        return {
            "max": self.current_max,
            "min": self.current_min,
            "spread": self.current_min / max(0.00000001, self.current_max) - 1,
            "min_margin": self.current_price / max(0.00000001, self.current_min) - 1,
            "temperature": temperature,
            "within_band": not outside_band,
            "current": self.current_price,
            "change": self.last_change,
            "state": self.read_state(),
            "fee_ratio": fee_ratio,
            "round": round,
            "buy": {
                "price": self.read_num("buy_price"),
                "trigger": self.read_num("buy_trigger_price"),
                "trigger_max": self.read_num("buy_trigger_max"),
                "amount": self.read_num("buy_amount"),
                "value": self.read_num("buy_value"),
                "cost": self.read_num("buy_cost"),
                "fees": self.read_num("buy_fees"),
                "time": self.read_num("buy_time"),
            },
            "sell": {
                "price": self.read_num("sell_price"),
                "amount": self.read_num("sell_amount"),
                "value": self.read_num("sell_value"),
                "revenue": self.read_num("sell_revenue"),
                "fees": self.read_num("sell_fees"),
                "time": self.read_num("sell_time"),
                "net_price": self.read_num("net_sell_price"),
            },
            "cashflow": self.get_cashflow(),
            "margin": self.read_num("margin"),
            "net_margin": self.read_num("net_margin"),
        }

    def get_portfolio(self):
        accounts = self.get_accounts()
        cfg = self.config
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
                    xchg = self.get_xchg_rate()
                    equity += float(account["balance"]) * xchg
                    avail_equity += float(account["available"]) * xchg
                holdings[account["currency"]] = {
                    "balance": account["balance"],
                    "hold": account["hold"],
                    "available": account["available"],
                }
        return {"equity": {"balance": equity, "available": avail_equity}, "holdings": holdings}


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
        self.channels = [{"name": "ticker", "product_ids": [self.pair]}]
        logger.info("Websocket client opened")

    def on_message(self, msg):
        if "price" in msg and "type" in msg:
            self.parent.on_price(msg)

    def on_close(self):
        self.parent.on_ws_dead()
