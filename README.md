# Trader

Python trading bot

## Prerequisites
 - Redis
 - Python 3.8 with updated pip (tested with 3.8.7)
 - Create copy of `resources/template.yaml`, call it `resources/config.yaml` and configure your bot there

# Installing
```bash
# Create virtual env first and install dependencies
py -3.8 -m venv venv
venv/bin/activate
pip install poetry
poetry install
```
For Windows, use `venv/Scripts/activate` instead. On some Linux distros, you might need to run it as `source venv/bin/activate`.

# Running
First of all, make sure you are in (venv), if not use `venv/bin/activate` again to get into virtual environment.

Run the following command to run trader server:
```bash
# Run trader
uvicorn trader.server:app --port 8000
```

# Running simulations
In order to run simulation, C++17 compiler is required, i.e. clang or gcc or even MSVC.
To compile simulations, run:
```bash
clang -O3 cpp/main.cpp -std=c++17 -o cpp/main.exe
```
To run simulations, run:
```
cpp/main --pair LTC-EUR
```
See `cpp/main -h` to see more options.