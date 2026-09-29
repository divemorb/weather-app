# Local weather aggregation service (non-commercial use)
# Data: DWD via Bright Sky + Open-Meteo (free, no API key required)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Unprivileged user (uid 1000) the app runs as; only /data and /tmp are
# writable at runtime (volume + tmpfs in docker-compose.yml)
RUN useradd --system --uid 1000 --no-create-home app

WORKDIR /app

# Install dependencies first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY --chown=app:app app/ ./app/
COPY --chown=app:app weather.yaml ./weather.yaml

# SQLite cache lives here (mount a volume here to persist it)
RUN mkdir -p /data && chown app:app /data
ENV DATABASE_PATH=/data/weather.db

EXPOSE 8000

USER app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
