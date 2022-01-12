from typing import Optional

from trader.model import TradingStrategy
from trader.strategy.base import BaseStrategy


class Chad(BaseStrategy):
    def __init__(self, strategy: TradingStrategy) -> None:
        super().__init__(strategy)

    def will_buy(self, change, price, round) -> bool:
        return change <= self.strategy.buy[round % len(self.strategy.buy)]

    def will_sell(self, change, buy_price, price, round) -> bool:
        if buy_price is None:
            return False
        return (price / buy_price - 1) >= (self.strategy.sell[round % len(self.strategy.sell)])

    def sell_price(self, change, buy_price, price, round) -> Optional[float]:
        if buy_price is None:
            return None
        return buy_price * (1 + self.strategy.sell[round % len(self.strategy.sell)])

    def buy_price(self, change, max_price, price, round) -> Optional[float]:
        if max_price is None:
            return None
        return min(max_price * (1 + self.strategy.buy[round % len(self.strategy.buy)]), price)
