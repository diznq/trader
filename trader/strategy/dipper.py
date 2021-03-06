from typing import Optional
from trader.app.core import Trader

from trader.model import TradingStrategy
from trader.strategy.base import BaseStrategy, Params


class Dipper(BaseStrategy):
    def __init__(self, strategy: TradingStrategy) -> None:
        super().__init__(strategy)

    def will_buy(self, trader: Trader) -> bool:
        params: Params = self.get_params(trader)
        return params.change <= self.strategy.buy[trader.current_round % len(self.strategy.buy)]

    def will_sell(self, trader: Trader) -> bool:
        params: Params = self.get_params(trader)
        return (params.price / params.buy_price - 1) >= (self.strategy.sell[params.round % len(self.strategy.sell)])

    def sell_price(self, trader: Trader) -> Optional[float]:
        params: Params = self.get_params(trader)
        return max(params.buy_price, params.price) * (1 + self.strategy.sell[params.round % len(self.strategy.sell)])

    def buy_price(self, trader: Trader) -> Optional[float]:
        params: Params = self.get_params(trader)
        return min(params.max * (1 + self.strategy.buy[params.round % len(self.strategy.buy)]), params.price)
