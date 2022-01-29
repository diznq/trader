FROM python:3.8.7

COPY pyproject.toml poetry.lock /app/

WORKDIR /app

RUN pip install --upgrade pip
RUN pip install poetry
RUN poetry install

COPY trader     /app/trader
COPY data       /app/data
COPY logs       /app/logs
COPY resources  /app/resources

EXPOSE 8000

CMD poetry run uvicorn trader.server:app --port 8000 --host 0.0.0.0