from pydantic import BaseModel


class ApiKey(BaseModel):
    name: str
    passphrase: str
    key: str


class TradingStrategy(BaseModel):
    buy: float
    buy_underprice: float
    sell: float
    window: float


class Config(BaseModel):
    sandbox: bool
    currency: str
    target: str
    target_precision: int
    currency_precision: int
    trade_partition: float
    portfolio: str
    apikey: ApiKey
    sandbox_apikey: ApiKey
    strategy: TradingStrategy
    place_immediately: bool
    tick_rate: float
    autocancel: float
