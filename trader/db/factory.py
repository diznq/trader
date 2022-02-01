from redis import Redis

from trader.db.poordis import Poordis


def get_db(name: str):
    if name == "redis":
        return Redis
    elif name == "poordis":
        return Poordis