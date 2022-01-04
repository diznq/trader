from trader.model import TradingStrategy

class BaseStrategy:
    strategy: TradingStrategy

    def __init__(self, strategy: TradingStrategy) -> None:
        self.strategy = strategy

    def will_buy(self, change, price) -> bool:
        return False

    def will_sell(self, change, buy_price, price) -> bool:
        return False