from trader.model import TradingStrategy
from trader.strategy.base import BaseStrategy

class Chad(BaseStrategy):
    def __init__(self, strategy: TradingStrategy) -> None:
        super().__init__(strategy)

    def will_buy(self, change, price) -> bool:
        return change <= self.strategy.buy

    def will_sell(self, change, buy_price, price) -> bool:
        if buy_price is None:
            return False
        return (price / buy_price - 1) >= (self.strategy.sell + self.strategy.taker + self.strategy.maker)

    def sell_price(self, change, buy_price, price) -> float:
        if buy_price is None:
            return None
        return buy_price * (1 + self.strategy.maker + self.strategy.taker + self.strategy.sell)