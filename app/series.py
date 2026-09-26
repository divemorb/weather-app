"""Pure helpers that shape parsed model/radar data into API-ready series (no I/O).

  * ``build_24h_series``            — hourly precipitation per model on a
                                      common UTC grid (24 h chart data)
  * ``build_radar_next_hour_bar``   — 12 x 5-min local-rain bar (radar nowcast)
  * ``build_forecast_history_rows`` — rows for the forecast_history table
                                      (optional accuracy extension, step 6)
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .models import ForecastBundle, Model24hSeries, RadarNowcast
from .probability import max_local_rain_mm
from .times import to_iso


def build_24h_series(
    bundle: ForecastBundle | None, n_hours: int = 24
) -> dict[str, Any]:
    """Hourly precipitation per model for the next ``n_hours`` hours.

    All models from one Open-Meteo call share the same hourly axis, so the
    grid is taken from the first model with data; a model whose axis does
    not match is skipped rather than misaligned. ``hours`` are ISO-8601 UTC
    strings. Returns ``{"hours": [...], "models": [...], "n_models": n}``
    where each entry in ``models`` is a dict with name + precipitation_mm.
    """
    if bundle is None:
        return {"hours": [], "models": [], "n_models": 0}
    reference = next(
        (m for m in bundle.models if m.hourly_time and m.hourly_precip_mm), None
    )
    if reference is None:
        return {"hours": [], "models": [], "n_models": 0}

    hours = reference.hourly_time[:n_hours]
    n = len(hours)
    models: list[dict[str, Any]] = []
    for m in bundle.models:
        if not m.hourly_time or m.hourly_time[:n] != hours:
            continue
        models.append(
            {
                "name": m.name,
                "precipitation_mm": list(m.hourly_precip_mm[:n]),
            }
        )
    return {
        "hours": [to_iso(t) for t in hours],
        "models": models,
        "n_models": len(models),
    }


def build_radar_next_hour_bar(
    nowcast: RadarNowcast | None,
    now: datetime,
    radius_km: float,
    cell_km: float,
    cell_rain_threshold_mm: float,
    n_steps: int = 12,
) -> dict[str, Any]:
    """12 five-minute buckets of the *local* (within ``radius_km``) radar rain
    for the next hour, for the 60-minute bar in the UI.

    Returns ``{"available": bool, "steps": [{"start_utc", "precip_mm"}, ...]}``
    with exactly ``n_steps`` buckets (oldest first). ``precip_mm`` is the
    strongest rain cell within the radius in that bucket (0.0 for dry); a
    bucket with no radar frame yet is 0.0. ``available`` is False when radar
    is missing or does not cover the location (the frontend then falls back to
    a models-only display).

    ``now`` is floored to the 5-minute grid before the buckets are laid out,
    so every bucket start sits on the same grid as the radar frame
    timestamps (the client floors its request the same way) — this is what
    makes frame-to-bucket matching exact rather than approximate.
    """
    grid_now = now.replace(
        minute=(now.minute // 5) * 5, second=0, microsecond=0
    )
    bucket_starts = [grid_now + timedelta(minutes=5 * i) for i in range(n_steps)]
    steps: list[dict[str, Any]] = [
        {"start_utc": to_iso(t), "precip_mm": 0.0} for t in bucket_starts
    ]

    if nowcast is None or not nowcast.covered or not nowcast.frames:
        return {"available": False, "steps": steps}

    frames_by_time = {frame.time_utc: frame for frame in nowcast.frames}
    for i, start in enumerate(bucket_starts):
        frame = frames_by_time.get(start)
        if frame is None:
            continue
        mm = max_local_rain_mm(
            nowcast, frame, radius_km, cell_km, cell_rain_threshold_mm
        )
        steps[i]["precip_mm"] = round(mm, 2)

    return {"available": True, "steps": steps}


def build_forecast_history_rows(
    bundle: ForecastBundle, issued_at: datetime, n_hours: int = 24
) -> list[dict[str, Any]]:
    """One row per model per hour for the next ``n_hours`` hours.

    Rows with null precipitation are skipped (nothing to verify later).
    ``issued_at`` is the moment the forecast was fetched.
    """
    rows: list[dict[str, Any]] = []
    for m in bundle.models:
        if not m.hourly_time:
            continue
        for t, v in zip(m.hourly_time[:n_hours], m.hourly_precip_mm[:n_hours]):
            if v is None:
                continue
            rows.append(
                {
                    "model": m.name,
                    "issued_at": to_iso(issued_at),
                    "valid_from": to_iso(t),
                    "valid_to": to_iso(t + timedelta(hours=1)),
                    "precip_mm": float(v),
                }
            )
    return rows
