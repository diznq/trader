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

class Config(BaseModel):
    currency: str
    pair: str
    portfolio: str
    apikeys: List[ApiKey]
    strategy: TradingStrategy