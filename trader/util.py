import os

import yaml

from trader.model import Config


def add_envs(obj, history):
    for key in obj:
        current = history + [key]
        path = "_".join(current)
        if isinstance(obj[key], dict):
            add_envs(obj[key], current)
        elif not isinstance(obj[key], list):
            t = type(obj[key])
            value = os.getenv(path, str(obj[key]))
            if isinstance(obj[key], bool):
                t = lambda x: {"true": True, "false": False}[x.lower()]
            obj[key] = t(value)


def load_config() -> Config:
    with open("./resources/config.yaml", "r", encoding="utf-8") as f:
        obj = yaml.safe_load(f)
        add_envs(obj, [])
        return Config.parse_obj(obj)
