from trader.model import TradingStrategy
from trader.strategy.base import BaseStrategy
from trader.strategy.dipper import Dipper
from trader.strategy.yolo import Yolo


def get_strategy(name: str, strategy: TradingStrategy) -> BaseStrategy:
    classes = {"dipper": Dipper, "yolo": Yolo}
    if name not in classes:
        name = "dipper"
    trader = classes[name]
    return trader(strategy)
