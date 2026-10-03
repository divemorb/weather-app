"""FastAPI application entrypoint.

REST contract (all times UTC; the frontend converts to the configured
display timezone):

  GET /healthz                  -> {"status": "ok", ...}
  GET /api/config               -> configured flag + location, timezone, weights
  GET /api/now                  -> current conditions tile + data age
  GET /api/rain-probability     -> combined % + per-source breakdown
  GET /api/radar/next-hour      -> 12 x 5-min radar bar (mm per step)
  GET /api/models/24h           -> hourly precipitation per model (24 points)
  GET /api/model-accuracy       -> per-model forecast accuracy (window)
  GET /api/sources              -> per-source age / staleness / errors
  GET /api/schedule             -> next backend refresh per job (UI countdown)
  GET /api/geocode              -> address search results (setup wizard)
  POST /api/location            -> set the home location (setup wizard)

Static frontend:  GET / (static/index.html)
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
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
from .config import AppConfig, LocationConfig, _env_bool, load_config
from .geocode import Geocoder
from .location import (
    LocationIn,
    location_payload,
    resolve_startup_location,
    same_origin,
    valid_timezone,
)
from .openmeteo_client import OpenMeteoClient
from .scheduler import build_scheduler, initial_refresh, schedule_models_retry, schedule_status
from .store import Store
from .upstream import SourceError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("weather")

_STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load_config()
    store = Store(cfg.database_path)
    await store.connect()

    # The location is runtime state: the stored value wins over env/YAML,
    # which is only adopted on first start (written to the DB).
    cfg = replace(cfg, location=await resolve_startup_location(store, cfg))

    brightsky = BrightSkyClient(cfg)
    openmeteo = OpenMeteoClient(cfg)
    geocoder = Geocoder(cfg.api.nominatim_base_url)  # address search
    aggregator = Aggregator(cfg, store, brightsky, openmeteo)

    scheduler = build_scheduler(cfg, aggregator)
    scheduler.start()
    # Warm the cache at startup; a failing source must not block startup.
    await initial_refresh(aggregator)
    schedule_models_retry(scheduler, aggregator, cfg)

    app.state.cfg = cfg
    app.state.aggregator = aggregator
    app.state.scheduler = scheduler
    app.state.geocoder = geocoder
    log.info("weather app started (db=%s)", cfg.database_path)
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        await brightsky.aclose()
        await openmeteo.aclose()
        await geocoder.aclose()
        await store.close()


# API docs are off by default: the app is a no-login LAN app, so the full
# API contract should not be browsable by every device on the network.
# Enable with ENABLE_API_DOCS=true (development only).
_docs_enabled = _env_bool("ENABLE_API_DOCS", False)

app = FastAPI(
    title="Local Weather Aggregator",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

# No CORSMiddleware on purpose: the frontend is same-origin, so CORS is not
# needed. Without CORS headers, a foreign website can still *send* a request
# to the API but cannot *read* the answer (opaque response), which closes
# the leak of the home location from /api/config.

# Security headers on every response: API, static files and error responses
# alike (the middleware below also answers unhandled 500s).
#   CSP            default-src 'self' — no external scripts/styles/frames
#                  (img-src data: for the inline favicon in index.html);
#                  object-src/base-uri/form-action/frame-ancestors locked
#                  down so the page can't embed, navigate or frame anything.
#   nosniff        stop browsers from MIME-sniffing a mis-served file
#   no-referrer    never leak the page URL to other origins
#   CORP           refuse to serve this app's files as cross-origin resources
_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; object-src 'none'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
}


# Host header check: the app only answers requests whose Host header names
# this app — an IP literal, localhost, a .local mDNS name, or one of
# ALLOWED_HOSTS (port ignored). Any other domain (e.g. a rebinding attack
# from evil.example) is rejected with 400, so a website whose DNS flips to
# this host's LAN IP can never be treated as same-origin.
_EXTRA_HOSTS = frozenset(
    h.strip().lower() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()
)


def host_allowed(host_header: str, extra: frozenset[str] = _EXTRA_HOSTS) -> bool:
    """True if the Host header names this app: an IP literal, localhost,
    a .local mDNS name, or one of ``extra`` (port ignored)."""
    host = host_header.strip().lower()
    if host.startswith("["):  # [::1]:8000
        host = host[1:].split("]", 1)[0]
    elif host.count(":") == 1:  # name:port or ipv4:port
        host = host.rsplit(":", 1)[0]
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    return host == "localhost" or host.endswith(".local") or host in extra


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    if not host_allowed(request.headers.get("host", "")):
        response = PlainTextResponse("Invalid host header", status_code=400)
    else:
        # Unhandled endpoint exceptions must not escape as a bare Starlette 500
        # (which would skip this middleware and lose the security headers).
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled error in %s", request.url.path)
            response = PlainTextResponse("Internal Server Error", status_code=500)
    for name, value in _SECURITY_HEADERS.items():
        response.headers[name] = value
    # Without Cache-Control the browser guesses a freshness period and keeps
    # using an old app.js after an update. "no-cache" makes it revalidate
    # every time; unchanged static files still answer 304 via their ETag.
    response.headers["Cache-Control"] = "no-cache"
    return response


# FastAPI's default 422 handler echoes the rejected input; a JSON body with
# NaN would then crash JSON rendering (500). Answer with the error messages
# only — never the input.
@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(
        {"detail": [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]},
        status_code=422,
    )


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/api/config")
async def api_config(request: Request) -> dict:
    cfg: AppConfig = request.app.state.cfg
    return {
        # "configured" tells the frontend whether to show the setup wizard;
        # "location" is null while unconfigured.
        "configured": cfg.location is not None,
        "location": location_payload(cfg.location) if cfg.location is not None else None,
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
    payload = await agg.get_current_payload()
    return serialize_now(conditions, meta, payload)


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
    """Per-model accuracy over the configured window.

    Compares stored forecasts against observed rain using the same
    ``> model_rain_threshold_mm`` event the next-hour vote uses. Returns an
    empty ``models`` dict while nothing has been compared yet, and
    ``stations`` (the observation stations) ``[]`` until the backfill has
    remembered any.
    """
    agg: Aggregator = request.app.state.aggregator
    cfg: AppConfig = request.app.state.cfg
    models = await agg.get_model_accuracy()
    stations = await agg.get_observation_stations()
    return serialize_model_accuracy(
        models, cfg.accuracy.window_days, cfg.accuracy.min_samples, stations
    )


@app.get("/api/sources")
async def api_sources(request: Request) -> dict:
    agg: Aggregator = request.app.state.aggregator
    return await agg.get_source_status()


@app.get("/api/schedule")
async def api_schedule(request: Request) -> dict:
    """Next backend refresh per job (radar / models), for the UI countdown."""
    cfg: AppConfig = request.app.state.cfg
    scheduler = getattr(request.app.state, "scheduler", None)
    return schedule_status(scheduler, cfg)


@app.get("/api/geocode")
async def api_geocode(
    request: Request,
    q: str = Query(min_length=3, max_length=200, description="Address or place"),
) -> dict:
    """Address search for the setup wizard (Nominatim).

    The typed text goes to OpenStreetMap Nominatim *from the app's server*
    (coordinates entered directly never leave the app). A failed lookup is
    a 502, never a 500: a failing source must not block the app.
    """
    geocoder: Geocoder = request.app.state.geocoder
    try:
        results = await geocoder.search(q)
    except SourceError:
        log.warning("address lookup failed for %r", q[:50])
        return JSONResponse({"detail": "address lookup failed"}, status_code=502)
    return {"results": results}


#: Keeps references to fire-and-forget refresh tasks so they are not
#: garbage-collected mid-flight.
_background_tasks: set[asyncio.Task] = set()


@app.post("/api/location")
async def api_set_location(request: Request, body: LocationIn) -> dict:
    """Set the home location (setup wizard).

    Same-origin JSON only: a foreign page can *send* a POST to a LAN app
    even without CORS (CSRF), so the write is refused for foreign origins.
    Pydantic validation runs before this body, so an invalid body is a 422
    (never a 500: the custom handler echoes no input).
    """
    if not same_origin(request):
        return JSONResponse({"detail": "cross-site request refused"}, status_code=403)
    if not valid_timezone(body.timezone):
        return JSONResponse(
            {"detail": [{"loc": ["body", "timezone"], "msg": "unknown timezone"}]},
            status_code=422,
        )
    # 3 decimals ~ 100 m: enough for the 1 km radar grid, less precise than
    # a street address.
    loc = LocationConfig(
        latitude=round(body.latitude, 3),
        longitude=round(body.longitude, 3),
        timezone=body.timezone,
        label=body.label,
    )
    agg: Aggregator = request.app.state.aggregator
    await agg.set_location(loc)
    request.app.state.cfg = agg.cfg
    # One background refresh so data appears within seconds; the task is
    # kept in _background_tasks so it cannot be GC'd before it finishes.
    scheduler = getattr(request.app.state, "scheduler", None)

    async def _refresh() -> None:
        await initial_refresh(agg)
        schedule_models_retry(scheduler, agg, agg.cfg)

    task = asyncio.create_task(_refresh())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"ok": True, "location": location_payload(loc)}


if _STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
