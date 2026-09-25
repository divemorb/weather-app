# Local weather aggregation service (non-commercial use)
# Data: DWD via Bright Sky + Open-Meteo (free, no API key required)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY app/ ./app/
COPY config/ ./config/
COPY weather.yaml ./weather.yaml

# SQLite cache

