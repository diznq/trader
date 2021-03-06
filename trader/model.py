from typing import List, Optional

from pydantic import BaseModel


class ApiKey(BaseModel):
    name: str
    passphrase: str
    key: str


class TemperatureDef(BaseModel):
    enabled: bool
    min: float
    max: float
    window: int


class TradingStrategy(BaseModel):
    buy: List[float]
    buy_underprice: float
    sell: List[float]
    window: float
    extra: Optional[object]


class Config(BaseModel):
    sandbox: bool
    forex: bool = False
    db: str = "redis"
    initial_dataset: Optional[str] = "stock_dataset.csv"
    currency: str
    target: str
    target_precision: int
    currency_precision: int
    trade_partition: float
    portfolio: str
    apikey: ApiKey
    sandbox_apikey: ApiKey
    trader: str = "dipper"
    strategy: TradingStrategy
    place_immediately: bool
    tick_rate: float
    autocancel: float
    temperature: TemperatureDef
