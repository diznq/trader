import json
import os
import time
from threading import Lock
from typing import Optional

class Poordis:
    lock = Lock()

    def __init__(self, **kwargs) -> None:
        pass

    def load_data(self):
        if not os.path.exists("data/poordis.json"):
            return {}
        with open("data/poordis.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            return data
    
    def store_data(self, data):
        with open("data/poordis.json", "w", encoding="utf-8") as f:
            json.dump(data, f)

    def get(self, key: str) -> Optional[bytes]:
        with self.lock:
            data = self.load_data()
            if key not in data:
                return None
            item = data[key]
            if item[1] > 0 and time.time() > item[1]:
                return None
            return str(item[0]).encode("utf-8")

    def setex(self, key: str, ex: Optional[int], value) -> bool:
        with self.lock:
            data = self.load_data()
            if ex is not None:
                ex = time.time() + ex
            else:
                ex = 0
            data[key] = [str(value), ex]
            self.store_data(data)
            return True

    def set(self, key: str, value) -> bool:
        return self.setex(key, None, value)
