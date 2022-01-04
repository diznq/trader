from fastapi import FastAPI

from trader.util import load_config

app = FastAPI()
cfg = load_config()

@app.get("/")
async def root():
    return load_config()