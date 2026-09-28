"""FastAPI application entrypoint.

REST contract (all times UTC; the frontend converts to the configured
display timezone):

  GET /healthz                  -> {"status": "ok", ...}
  GET /api/config               -> location, timezone, weights (for UI labels)
  GET /api/now                  -> current conditions tile + data age
  GET /api/rain-probability     -> combined % + per-source breakdown
  GET /api/radar/next-hour      -> 12 x 5-min radar bar (mm per step)
  GET /api/models/24h           -> hourly precipitation per model (24 points)
  GET /api/model-accuracy       -> per-model forecast accuracy (window, 6e)
  GET /api/sources              -> per-source age / staleness / errors

Static frontend:  GET / (static/index.html, step 5)
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .aggregator import Aggregator
from .api_serializers import (
    serialize_model_accuracy,
    serialize_models_24h,
    serialize_now,
    serialize_radar_next_hour,
    serialize_rain_probability,
)
from .brightsky_client import BrightSkyClient
from .config import AppConfig, load_config
from .openmeteo_client import OpenMeteoClient
from .scheduler import build_scheduler, initial_refresh
from .store import Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("weather")

_STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load_config()
    store = Store(cfg.database_path)
    await store.connect()

    brightsky = BrightSkyClient(cfg)
    openmeteo = OpenMeteoClient(cfg)
    aggregator = Aggregator(cfg, store, brightsky, openmeteo)

    scheduler = build_scheduler(cfg, aggregator)
    scheduler.start()
    # Warm the cache at startup; a failing source must not block startup.
    await initial_refresh(aggregator)

    app.state.cfg = cfg
    app.state.aggregator = aggregator
    log.info("weather app started (db=%s)", cfg.database_path)
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        await brightsky.aclose()
        await openmeteo.aclose()
        await store.close()


app = FastAPI(title="Local Weather Aggregator", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # local network app
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/api/config")
async def api_config(request: Request) -> dict:
    cfg: AppConfig = request.app.state.cfg
    return {
        "location": {
            "latitude": cfg.location.latitude,
            "longitude": cfg.location.longitude,
            "timezone": cfg.location.timezone,
        },
        "radar_radius_km": cfg.radar.radius_km,
        "weights": {
            "radar": cfg.probability.weight_radar,
            "models": cfg.probability.weight_models,
            "ensemble": cfg.probability.weight_ensemble,
        },
        "models": list(cfg.models.forecast),
    }


@app.get("/api/now")
async def api_now(request: Request) -> dict:
    agg: Aggregator = request.app.state.aggregator
    conditions = await agg.get_current_conditions()
    meta = await agg.cache_meta("current")
    return serialize_now(conditions, meta)


@app.get("/api/rain-probability")
async def api_rain_probability(request: Request) -> dict:
    agg: Aggregator = request.app.state.aggregator
    rain = await agg.get_rain_probability()
    radar_meta = await agg.cache_meta("radar")
    models_meta = await agg.cache_meta("forecast")
    return serialize_rain_probability(rain, radar_meta, models_meta)


@app.get("/api/radar/next-hour")
async def api_radar_next_hour(request: Request) -> dict:
    agg: Aggregator = request.app.state.aggregator
    bar = await agg.get_radar_next_hour()
    meta = await agg.cache_meta("radar")
    return serialize_radar_next_hour(bar, meta)


@app.get("/api/models/24h")
async def api_models_24h(request: Request) -> dict:
    agg: Aggregator = request.app.state.aggregator
    series = await agg.get_24h_model_comparison()
    meta = await agg.cache_meta("forecast")
    return serialize_models_24h(series, meta)


@app.get("/api/model-accuracy")
async def api_model_accuracy(request: Request) -> dict:
    """Per-model accuracy over the configured window (step 6e).

    Compares stored forecasts against observed rain using the same
    ``> model_rain_threshold_mm`` event the next-hour vote uses. Returns an
    empty ``models`` dict while nothing has been compared yet.
    """
    agg: Aggregator = request.app.state.aggregator
    cfg: AppConfig = request.app.state.cfg
    models = await agg.get_model_accuracy()
    return serialize_model_accuracy(
        models, cfg.accuracy.window_days, cfg.accuracy.min_samples
    )


@app.get("/api/sources")
async def api_sources(request: Request) -> dict:
    agg: Aggregator = request.app.state.aggregator
    return await agg.get_source_status()


if _STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
