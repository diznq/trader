from typing import List
from pydantic import BaseModel

class ApiKey(BaseModel):
    name: str
    passphrase: str
    key: str
    permissions: List[str]
    portfolio: str

class TradingStrategy(BaseModel):
    buy: float
    sell: float
    maker: float
    taker: float
    window: float

class Config(BaseModel):
    currency: str
    target: str
    target_precision: int
    currency_precision: int
    portfolio: str
    apikey: ApiKey
    strategy: TradingStrategy