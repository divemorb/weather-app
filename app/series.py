"""Pure helpers that shape parsed model/radar data into API-ready series (no I/O).

  * ``build_24h_series``            — hourly precipitation per model on a
                                      common UTC grid (24 h chart data)
  * ``build_radar_next_hour_bar``   — 12 x 5-min local-rain bar (radar nowcast)
  * ``build_forecast_history_rows`` — rows for the forecast_history table
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .models import ForecastBundle, Model24hSeries, RadarNowcast
from .probability import max_local_rain_mm
from .times import to_iso


def build_24h_series(
    bundle: ForecastBundle | None, now: datetime, n_hours: int = 24
) -> dict[str, Any]:
    """Hourly precipitation per model for the next ``n_hours`` hours.

    The axis is relative to ``now`` (not the UTC day): only stamps
    ``t > now`` are kept. Convention: the hourly value at stamp ``t`` is
    the rain of the preceding hour ``[t-1h, t)``, so ``hours[i]`` carries
    the hour's *start* (``t - 1h``) for the value ``precipitation_mm[i]``.

    The common grid is taken from the first model with data; a model whose
    axis does not match is skipped. ``hours`` are ISO-8601 UTC strings; the
    return shape is ``{"hours", "models", "n_models"}`` where each model
    entry has name + precipitation_mm.
    """
    if bundle is None:
        return {"hours": [], "models": [], "n_models": 0}
    reference = next(
        (m for m in bundle.models if m.hourly_time and m.hourly_precip_mm), None
    )
    if reference is None:
        return {"hours": [], "models": [], "n_models": 0}

    stamps = [t for t in reference.hourly_time if t > now][:n_hours]
    n = len(stamps)
    if n == 0:
        return {"hours": [], "models": [], "n_models": 0}
    # the window starts at an arbitrary offset into the axis (it is
    # relative to now); align every model at the reference's offset
    offset = reference.hourly_time.index(stamps[0])
    models: list[dict[str, Any]] = []
    for m in bundle.models:
        if not m.hourly_time or len(m.hourly_time) < offset + n:
            continue
        if m.hourly_time[offset : offset + n] != stamps:
            continue
        values = list(m.hourly_precip_mm[offset : offset + n])
        if all(v is None for v in values):
            continue  # model with null data draws nothing -> skip
        models.append(
            {
                "name": m.name,
                "precipitation_mm": values,
            }
        )
    if not models:  # every model has null data -> same empty shape as no bundle
        return {"hours": [], "models": [], "n_models": 0}
    # label each hour by its START (the value at stamp t covers [t-1h, t))
    return {
        "hours": [to_iso(t - timedelta(hours=1)) for t in stamps],
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
    with exactly ``n_steps`` buckets (oldest first); ``precip_mm`` is the
    strongest rain cell within the radius in that bucket (0.0 for dry or
    when no frame covers it). ``available`` is False when radar is missing
    or does not cover the location (the frontend falls back to models-only).

    ``now`` is floored to the 5-minute grid so every bucket start sits on
    the same grid as the radar frame timestamps (the client floors its
    request the same way) — this makes frame-to-bucket matching exact.
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
    """One row per model per hour that has *not started yet* at ``issued_at``.

    The hourly value at stamp ``t`` covers the preceding hour ``[t-1h, t)``,
    so ``valid_from = t - 1h`` and ``valid_to = t`` (not ``t + 1h``). Hours
    already in progress are skipped: their value would be partially
    observed, biasing the accuracy comparison. Rows with null precipitation
    are skipped. ``issued_at`` is the moment the forecast was fetched.

    The ``n_hours`` cap is on *future* hours: with the 3-day axis, a raw
    slice would drop next-day hours when issued late in the UTC day.
    """
    rows: list[dict[str, Any]] = []
    for m in bundle.models:
        if not m.hourly_time:
            continue
        model_rows: list[dict[str, Any]] = []
        for t, v in zip(m.hourly_time, m.hourly_precip_mm):
            if v is None:
                continue
            valid_from = t - timedelta(hours=1)
            if valid_from < issued_at:
                continue  # hour already started: not a (future) forecast
            model_rows.append(
                {
                    "model": m.name,
                    "issued_at": to_iso(issued_at),
                    "valid_from": to_iso(valid_from),
                    "valid_to": to_iso(t),
                    "precip_mm": float(v),
                }
            )
            if len(model_rows) == n_hours:
                break
        rows.extend(model_rows)
    return rows
