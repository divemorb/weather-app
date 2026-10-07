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
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, ValidationInfo, field_validator

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
