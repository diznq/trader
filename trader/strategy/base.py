from dataclasses import dataclass
from typing import Optional

from trader.model import TradingStrategy

@dataclass
class Params:
    buy_price: Optional[float]
    sell_price: Optional[float]
    price: float
    change: float
    round: int
    max: Optional[float]
    min: Optional[float]
    temperature: float


class BaseStrategy:
    strategy: TradingStrategy

    def __init__(self, strategy: TradingStrategy) -> None:
        self.strategy = strategy

    def will_buy(self, trader) -> bool:
        return False

    def will_sell(self, trader) -> bool:
        return False

    def sell_price(self, trader) -> Optional[float]:
        return None

    def buy_price(self, trader) -> Optional[float]:
        return None

    def get_params(self, trader) -> Params:
        return Params(
            buy_price=trader.read_num("buy_price"),
            sell_price=trader.read_num("sell_price"),
            price=trader.current_price,
            change=trader.last_change,
            round=trader.current_round,
            max=trader.current_max,
            min=trader.current_min,
            temperature=trader.current_temperature
        )

