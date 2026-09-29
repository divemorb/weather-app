"""Location as runtime state (step 8b).

The home location is no longer a fixed configuration: it is stored in the
database (``app_meta`` key ``"location"``) and can be set or changed from
the browser (setup wizard, step 8d). On startup the stored value wins; a
location from env/YAML is only *adopted* (written to the database) when
nothing is stored yet, so an existing install keeps its location when
``weather.yaml`` loses the ``location:`` block.

Everything here is a small pure helper plus one async function; the store
only moves data.
"""
from __future__ import annotations

import json
import logging
from dataclasses import replace
from typing import Any

from .config import AppConfig, LocationConfig
from .store import Store

log = logging.getLogger("weather.location")

#: ``app_meta`` key holding the JSON location (see :func:`location_to_json`).
LOCATION_KEY = "location"

#: Two locations closer than this (degrees, ~1 km) count as "the same".
MOVED_EPSILON = 0.01


def location_to_json(loc: LocationConfig) -> str:
    """Serialize a location to the JSON stored in ``app_meta``."""
    return json.dumps(
        {
            "latitude": loc.latitude,
            "longitude": loc.longitude,
            "timezone": loc.timezone,
            "label": loc.label,
        }
    )


def location_from_json(text: str | None) -> LocationConfig | None:
    """Parse the stored JSON; bad JSON, missing keys or wrong types -> None.

    Never raises: a corrupted value means "no stored location", which the
    startup resolution then falls back to env/YAML (or unconfigured).
    """
    if text is None:
        return None
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    lat = data.get("latitude")
    lon = data.get("longitude")
    if isinstance(lat, bool) or isinstance(lon, bool):
        return None
    if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))):
        return None
    tz = data.get("timezone")
    if not isinstance(tz, str) or not tz:
        return None
    label = data.get("label", "")
    if not isinstance(label, str):
        label = ""
    return LocationConfig(latitude=float(lat), longitude=float(lon), timezone=tz, label=label)


def moved(old: LocationConfig | None, new: LocationConfig) -> bool:
    """True when ``new`` is a *different* location than ``old``.

    ``old is None`` (first location ever) is not a move: there is nothing to
    throw away. Otherwise latitude **or** longitude differing by more than
    ``MOVED_EPSILON`` (≈1 km) counts as moved.
    """
    if old is None:
        return False
    return abs(old.latitude - new.latitude) > MOVED_EPSILON or abs(
        old.longitude - new.longitude
    ) > MOVED_EPSILON


async def resolve_startup_location(
    store: Store, cfg: AppConfig
) -> LocationConfig | None:
    """The location the app starts with (step 8b).

    Precedence: the stored ``app_meta`` location wins; else the env/YAML
    location from the config is *adopted* (written to the database so it
    survives a ``weather.yaml`` that later loses the block); else ``None``
    (unconfigured — the setup wizard will ask).
    """
    stored = location_from_json(await store.get_meta(LOCATION_KEY))
    if stored is not None:
        return stored
    if cfg.location is not None:
        await store.set_meta(LOCATION_KEY, location_to_json(cfg.location))
        log.info(
            "adopting configured location %s,%s into the database",
            cfg.location.latitude,
            cfg.location.longitude,
        )
        return cfg.location
    return None


def location_payload(loc: LocationConfig) -> dict[str, Any]:
    """JSON shape of a location for API responses (``/api/config`` etc.)."""
    return {
        "latitude": loc.latitude,
        "longitude": loc.longitude,
        "timezone": loc.timezone,
        "label": loc.label,
    }


async def apply_location(
    store: Store,
    cfg: AppConfig,
    brightsky: Any,
    openmeteo: Any,
    loc: LocationConfig,
) -> AppConfig:
    """Make ``loc`` the effective location (step 8b) and return the new cfg.

    When the location actually *moved* (more than ~1 km away), all data
    belonging to the old location is deleted first (``clear_location_data``).
    Then the location is persisted (``app_meta``), pushed to both clients
    (``set_location``) and the effective config is returned with the new
    location. A first location (``cfg.location is None``) stores without
    clearing — there is nothing to throw away.
    """
    if moved(cfg.location, loc):
        await store.clear_location_data()
    await store.set_meta(LOCATION_KEY, location_to_json(loc))
    brightsky.set_location(loc.latitude, loc.longitude)
    openmeteo.set_location(loc.latitude, loc.longitude)
    return replace(cfg, location=loc)
