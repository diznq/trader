import yaml
from trader.model import Config

def load_config() -> Config:
    with open("./resources/config.yaml", "r", encoding="utf-8") as f:
        obj = yaml.safe_load(f)
        return Config.parse_obj(obj)