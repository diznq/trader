from typing import Optional

from trader.model import TradingStrategy


class BaseStrategy:
    strategy: TradingStrategy

    def __init__(self, strategy: TradingStrategy) -> None:
        self.strategy = strategy

    def will_buy(self, change, price, round) -> bool:
        return False

    def will_sell(self, change, buy_price, price, round) -> bool:
        return False

    def sell_price(self, change, buy_price, price, round) -> Optional[float]:
        return None

    def buy_price(self, change, max_price, price, round) -> Optional[float]:
        return None
