"""Pure helpers that shape parsed model data into API-ready series (no I/O).

  * ``build_24h_series``            — hourly precipitation per model on a
                                      common UTC grid (24 h chart data)
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
