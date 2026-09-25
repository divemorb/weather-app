"""Pure helpers that shape model data into API-ready series (no I/O).

  * ``build_24h_series``          — hourly precipitation per model, aligned
                                    to a common UTC grid (24 h chart data)
  * ``build_forecast_history_rows`` — rows for the forecast_history table
                                    (optional accuracy extension, step 6)
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .models import ForecastBundle, Model24hSeries
from .times import to_iso


def build_24h_series(
    bundle: ForecastBundle | None, n_hours: int = 24
) -> dict[str, Any]:
    """Hourly precipitation per model on a common UTC grid (chart data).

    All models from one Open-Meteo call share the same hourly axis, so the
    grid is taken from the first model with data; a model on a different
    axis is skipped rather than misaligned. ``hours`` are ISO-8601 UTC
    strings. Returns ``{"hours": [...], "models": [...], "n_models": n}``.
    """
    reference: Model24hSeries | None = None
    if bundle is not None:
        for m in bundle.models:
            if m.hourly_time and m.hourly_precip_mm:
                reference = m
                break
    if reference is None:
        return {"hours": [], "models": [], "n_models": 0}

    hours = reference.hourly_time[:n_hours]
    n = len(hours)
    series: list[Model24hSeries] = []
    for m in bundle.models:
        if not m.hourly_time:
            continue
        if m.hourly_time[:n] != hours:
            continue
        series.append(
            Model24hSeries(
                name=m.name,
                hours=list(hours),
                precipitation_mm=list(m.hourly_precip_mm[:n]),
            )
        )
    return {
        "hours": [to_iso(t) for t in hours],
        "models": series,
        "n_models": len(series),
    }


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
