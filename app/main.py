"""FastAPI application entrypoint.

REST contract (all times UTC; the frontend converts to the configured
display timezone):

  GET /healthz                  -> {"status": "ok", ...}
  GET /api/config               -> location, timezone, weights (for UI labels)
  GET /api/now                  -> current conditions tile + data age
  GET /api/rain-probability     -> combined % + per-source breakdown
  GET /api/radar/next-hour      -> 12 x 5-min radar bar (mm per step)
  GET /api/models/24h           -> hourly precipitation per model (24 points)
  GET /api/sources              -> per-source age / staleness / errors

Static frontend:  GET / (static/index.html, step 5)
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .aggregator import Aggregator
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


def _not_implemented() -> JSONResponse:
    return JSONResponse({"error": "not implemented yet (see step 3/4)"}, status_code=501)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/api/config")
async def api_config() -> dict:
    cfg: AppConfig = app.state.cfg
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
async def api_now():
    # step 4: return await app.state.aggregator.get_current_conditions()
    return _not_implemented()


@app.get("/api/rain-probability")
async def api_rain_probability():
    # step 4: return await app.state.aggregator.get_rain_probability()
    return _not_implemented()


@app.get("/api/radar/next-hour")
async def api_radar_next_hour():
    # step 4: 12 five-minute steps from the radar nowcast
    return _not_implemented()


@app.get("/api/models/24h")
async def api_models_24h():
    # step 4: hourly precipitation series per model
    return _not_implemented()


@app.get("/api/sources")
async def api_sources():
    # step 4: per-source cache age, staleness, last error
    return _not_implemented()


if _STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
