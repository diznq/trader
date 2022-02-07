from random import random
from typing import Optional
from trader.app.core import Trader

from trader.model import TradingStrategy
from trader.strategy.base import BaseStrategy, Params


class SmartYolo(BaseStrategy):
    def __init__(self, strategy: TradingStrategy) -> None:
        super().__init__(strategy)

    def will_buy(self, trader: Trader) -> bool:
        params = self.get_params(trader)
        if params.sell_price is not None and params.price > params.sell_price:
            return False
        return random() < self.strategy.buy[params.round % len(self.strategy.buy)]

    def will_sell(self, trader: Trader) -> bool:
        return True

    def sell_price(self, trader: Trader) -> Optional[float]:
        params: Params = self.get_params(trader)
        return params.buy_price * (1.01 + random() * self.strategy.sell[params.round % len(self.strategy.sell)])

    def buy_price(self, trader: Trader) -> Optional[float]:
        params: Params = self.get_params(trader)
        if params.max is None:
            return None
        return min(params.max * (1 + self.strategy.buy[round % len(self.strategy.buy)]), params.price)
