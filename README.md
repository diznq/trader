# Trader

Python trading bot

## Prerequisites
 - Python 3.8 with updated pip (tested with 3.8.7)
 - Create copy of `resources/template.yaml`, call it `resources/config.yaml` and configure your bot there

# Installing
```bash
# Create virtual env first and install dependencies
python -m venv venv
venv/bin/activate
pip install poetry
poetry install
```
For Windows, use `venv/Scripts/activate` instead.

# Running
First of all, make sure you are in (venv), if not use `venv/bin/activate` again to get into virtual environment.
Run following command to run trader server:
```bash
# Run trader
uvicorn trader.server:app --port 8000
```