from typing import List
from pydantic import BaseModel

class ApiKey(BaseModel):
    name: str
    passphrase: str
    key: str
    permissions: List[str]
    portfolio: str

class TradingStrategy(BaseModel):
    buy: -0.04
    sell: 0.025
    maker: 0.005
    taker: 0.005

class Config(BaseModel):
    apikeys: List[ApiKey]
    strategy: TradingStrategy