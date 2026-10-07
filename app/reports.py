"""User reports: what the sky really looks like ("Stimmt nicht?").

The user reports the real weather when the page is wrong — or confirms it
when it is right. The body is a closed set of values (unknown fields and
client times are refused); the *server's* clock sets the observation time
(``minutes_ago`` only moves it back by 0/15/30 whole minutes, truncated to
whole seconds). Reports are kept for the accuracy window (at most 500, the
newest survive) and go with the location's data on a move
(``Store.clear_location_data``).
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, ValidationInfo, field_validator

from .config import AppConfig
from .store import Store
from .times import to_iso, utcnow

#: The closed set of report kinds (what the sky looks like).
Kind = Literal["clear", "partly-cloudy", "cloudy", "fog", "rain", "thunderstorm", "snow", "hail"]
#: Rain intensity; may only be reported with ``kind = "rain"``.
Intensity = Literal["light", "moderate", "heavy"]

#: A report is *fresh* (the current one) while observed within these minutes.
FRESH_MINUTES = 30
#: At most this many reports are kept (the newest survive the pruning).
MAX_REPORTS = 500

#: ``DELETE /api/reports/{report_id}``: plain digits, no sign, no leading
#: zero, below 10**18 (anything else is a 422, e.g. ``+5``, ``05``, 19 digits).
REPORT_ID_PATTERN = r"^[1-9][0-9]{0,17}$"


class ReportIn(BaseModel):
    """Body of ``POST /api/reports`` (closed set; unknown fields are a 422)."""

    model_config = ConfigDict(extra="forbid")

    kind: Kind
    intensity: Intensity | None = None
    minutes_ago: StrictInt = 0
    confirms: StrictBool = False

    @field_validator("intensity")
    @classmethod
    def _intensity_only_with_rain(cls, value: Intensity | None, info: ValidationInfo) -> Intensity | None:
        if value is not None and info.data.get("kind") != "rain":
            raise ValueError("intensity is only reported for rain")
        return value

    @field_validator("minutes_ago")
    @classmethod
    def _minutes_ago_step(cls, value: int) -> int:
        if value not in (0, 15, 30):
            raise ValueError("minutes_ago must be 0, 15 or 30")
        return value


async def save_report(store: Store, body: ReportIn, window_days: int) -> dict:
    """Store a new report and return it (``id`` first, then the body's values
    with the server's ``observed_at``).

    Every save also prunes: reports observed before ``now - window_days``
    go, then all but the newest :data:`MAX_REPORTS` (``observed_at``, then
    ``id``) — so the table never outgrows the accuracy window or the cap.
    """
    now = utcnow()
    observed_at = to_iso(now - timedelta(minutes=body.minutes_ago))
    report_id = await store.add_report(body.kind, body.intensity, body.confirms, observed_at)
    await store.prune_reports(to_iso(now - timedelta(days=window_days)), MAX_REPORTS)
    return {
        "id": report_id,
        "kind": body.kind,
        "intensity": body.intensity,
        "confirms": body.confirms,
        "observed_at": observed_at,
    }


async def current_report(store: Store | None) -> dict | None:
    """The fresh report: the newest one observed within the last
    :data:`FRESH_MINUTES` minutes (both ends inclusive); None otherwise
    (no reports, none fresh, or no Store — endpoint tests with a fake
    aggregator have none)."""
    if store is None:
        return None
    row = await store.newest_report()
    if row is None:
        return None
    report_id, kind, intensity, confirms, observed_at = row
    now = utcnow()
    if not (to_iso(now - timedelta(minutes=FRESH_MINUTES)) <= observed_at <= to_iso(now)):
        return None
    return {
        "id": report_id,
        "kind": kind,
        "intensity": intensity,
        "confirms": bool(confirms),
        "observed_at": observed_at,
    }


async def delete_report(store: Store | None, report_id: int) -> bool:
    """Undo a report; True when the row existed (False also without a Store)."""
    if store is None:
        return False
    return await store.delete_report(report_id)


# ---------------------------------------------------------------------------
# P2: the models against the reports (``user_reports`` in
# ``/api/model-accuracy``)
# ---------------------------------------------------------------------------

#: The kinds that count as wet for the accuracy comparison; the other four
#: (``clear``, ``partly-cloudy``, ``cloudy``, ``fog``) are dry.
WET_KINDS = frozenset({"rain", "thunderstorm", "snow", "hail"})


def hour_of(observed_at: str) -> str:
    """The hour a report belongs to: ``observed_at`` cut to the hour
    (the ``valid_from`` format)."""
    return observed_at[:13] + ":00:00Z"


def deciding_reports(rows: list[tuple[int, str, bool, str]]) -> dict[str, tuple[bool, bool]]:
    """Per hour, the newest report's ``(wet, confirms)``.

    ``rows`` are the store's ``(id, kind, confirms, observed_at)``; the
    newest report of an hour (``observed_at``, then id) decides it.
    """
    newest: dict[str, tuple[str, int, str, bool]] = {}  # hour -> (observed_at, id, kind, confirms)
    for report_id, kind, confirms, observed_at in rows:
        hour = hour_of(observed_at)
        current = newest.get(hour)
        if current is None or (observed_at, report_id) > (current[0], current[1]):
            newest[hour] = (observed_at, report_id, kind, confirms)
    return {
        hour: (kind in WET_KINDS, confirms)
        for hour, (_observed_at, _report_id, kind, confirms) in newest.items()
    }


def score_user_reports(
    deciding: dict[str, tuple[bool, bool]],
    rows: list[tuple[str, str, float]],
    threshold_mm: float,
) -> dict[str, Any]:
    """Score the models against the user reports (the ``user_reports`` block).

    ``deciding`` is :func:`deciding_reports`; ``rows`` are the station's
    scored rows ``(model, valid_from, precip_mm)`` (``observed_mm IS NOT
    NULL``, the window). Only report hours with at least one such row are
    scored (``hours``), ``confirmed_hours`` counting those whose deciding
    report confirms. A model's forecast is wet when ``precip_mm >
    threshold_mm`` (strict, as in :mod:`app.accuracy`); the models come out
    in alphabetical order, like the station's table.
    """
    pairs: dict[str, list[tuple[bool, bool]]] = {}
    scored: set[str] = set()
    for model, valid_from, precip_mm in rows:
        report = deciding.get(valid_from)
        if report is None:
            continue
        wet, _confirms = report
        scored.add(valid_from)
        pairs.setdefault(model, []).append((precip_mm > threshold_mm, wet))
    confirmed_hours = sum(1 for hour in scored if deciding[hour][1])
    models: dict[str, dict[str, Any]] = {}
    for model in sorted(pairs):
        hits = misses = false_alarms = correct_negatives = 0
        for forecast_wet, observed_wet in pairs[model]:
            if forecast_wet and observed_wet:
                hits += 1
            elif observed_wet:
                misses += 1
            elif forecast_wet:
                false_alarms += 1
            else:
                correct_negatives += 1
        n = hits + misses + false_alarms + correct_negatives
        models[model] = {
            "n_samples": n,
            "hits": hits,
            "misses": misses,
            "false_alarms": false_alarms,
            "correct_negatives": correct_negatives,
            "event_accuracy": round((hits + correct_negatives) / n, 3) if n else None,
        }
    return {"hours": len(scored), "confirmed_hours": confirmed_hours, "models": models}


async def user_report_accuracy(store: Store | None, cfg: AppConfig) -> dict[str, Any]:
    """The ``user_reports`` block of ``/api/model-accuracy``.

    Scores the same rows the station uses (``observed_mm IS NOT NULL``, the
    window from this module's clock) against the newest user report of each
    hour; the empty block without a Store (endpoint tests with a fake
    aggregator have none).
    """
    if store is None:
        return {"hours": 0, "confirmed_hours": 0, "models": {}}
    now = utcnow()
    since = to_iso(now - timedelta(days=cfg.accuracy.window_days))
    return score_user_reports(
        deciding_reports(await store.report_rows()),
        await store.scored_forecasts(since),
        cfg.probability.model_rain_threshold_mm,
    )
