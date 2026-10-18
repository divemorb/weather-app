"""The day-light-saving checks for the rain page.

The page's clock is frozen at Berlin's CEST->CET switchover (a little after
midnight UTC on the switch night) while every one of the scenario's real API
answers is shifted by the same delta, so the data lines up with that moment.
The radar strip and the 24-hour chart must then show the wall-clock times
across the switch, where a fixed +02:00 offset is an hour late. The expected
strings come from the page's own Intl formatting (UIPage.times, the location's
zone), so the harness and the page can never disagree on the locale's shape.
"""

from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone

from expect import TZ
from page import Run, norm

DST_NOW = "2026-10-25T00:20:00Z"  # Berlin switches CEST->CET at 01:00 UTC, 20 min later than this
PATHS = ["/api/config", "/api/rain-probability", "/api/radar/next-hour", "/api/now",
         "/api/models/24h", "/api/sources", "/api/schedule", "/api/model-accuracy",
         "/api/reports/current"]  # the API paths a rain refresh reads (config once at startup)
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _get(base: str, path: str):
    """The app's real answer for one API path (status, decoded body; (0, None) on error)."""
    try:
        with urllib.request.urlopen(base + path, timeout=10) as r:
            return r.status, json.loads(r.read() or "null")
    except Exception:  # noqa: BLE001 - a missing answer just means "not faked"
        return 0, None


def _delta(run: Run) -> timedelta:
    """The shift that moves the scenario's "now" onto DST_NOW (the same for every path)."""
    return _parse(DST_NOW) - _parse(run.sc["now"])


def _parse(s: str) -> datetime:
    """A UTC datetime from a full ISO timestamp (the harness uses only these)."""
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def _parse_iso(s: str):
    """A UTC datetime when s is a full ISO timestamp, else None (date-only strings stay)."""
    if not isinstance(s, str) or not ISO_RE.match(s):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _shift(value, delta: timedelta):
    """A copy of a JSON value with every full ISO timestamp shifted by delta."""
    if isinstance(value, str):
        t = _parse_iso(value)
        return (t + delta).strftime("%Y-%m-%dT%H:%M:%SZ") if t else value
    if isinstance(value, dict):
        return {k: _shift(v, delta) for k, v in value.items()}
    if isinstance(value, list):
        return [_shift(v, delta) for v in value]
    return value


def dst_fakes(run: Run) -> dict:
    """Fakes for the whole rain page at DST_NOW: the app's real answer for every data
    path (it runs at the scenario's earlier "now"), each shifted by the same delta,
    with /api/config kept on the location's zone (Europe/Berlin)."""
    delta = _delta(run)
    fakes = {}
    for path in PATHS:
        status, body = _get(run.base, path)
        if status != 200 or body is None:
            continue
        if path == "/api/config" and isinstance(body.get("location"), dict):
            body["location"]["timezone"] = TZ
        fakes[path] = [(200, json.dumps(_shift(body, delta)))]
    return fakes


def _faked(fakes: dict, path: str):
    """The shifted fake body for one path (dst_fakes' JSON, decoded), or None."""
    item = fakes.get(path)
    return json.loads(item[0][1]) if item else None


def dst_radar_labels(run: Run) -> list[str]:
    """The radar strip's four labels at the CEST->CET switch: the first, fifth and
    ninth step and the end of the hour, in the location's wall-clock zone, so the
    repeated 02:20 shows twice (once CEST, once CET)."""
    fakes = dst_fakes(run)
    steps = (_faked(fakes, "/api/radar/next-hour") or {}).get("steps") or []
    starts = [s["start_utc"] for s in steps if isinstance(s, dict) and isinstance(s.get("start_utc"), str)]
    if len(starts) < 9:
        return [f"only {len(starts)} shifted radar steps, expected 12"]
    isos = starts + [_shift(starts[-1], timedelta(minutes=5))]  # the end of the hour
    pg = run.page(now=DST_NOW, fakes=fakes)
    try:
        ok = pg.times(isos)
        want = [ok[0], ok[4], ok[8], ok[-1]]  # glance.js labels steps 0, 4, 8 and the end
        got = [norm(e["text"]) for e in pg.ui("radar-label") if e["visible"]]
        return [] if got == want else [f"radar labels {got}, expected {want} "
                                       "(Berlin CEST->CET at 01:00 UTC)"]
    finally:
        run.done(pg)


def _label_every(client_width: float) -> int:
    """The chart's label step, exactly as chart.js computes it for the big (non-kiosk)
    view: a narrow container labels every 6th hour, a wide one every 3rd."""
    w = round(max(300, min(1800, client_width or 720)))
    return 6 if w < 520 else 3


def dst_chart_x_labels(run: Run) -> list[str]:
    """The 24-hour chart's x labels at the CEST->CET switch: one per labelEvery-th
    hour, in the location's wall-clock zone, so the repeated 02:30 hour (CEST and
    CET) is drawn in the plot and its labelled hours keep the zone's true times."""
    fakes = dst_fakes(run)
    hours = (_faked(fakes, "/api/models/24h") or {}).get("hours") or []
    if len(hours) < 24:
        return [f"only {len(hours)} shifted chart hours, expected 24"]
    pg = run.page(now=DST_NOW, fakes=fakes)
    try:
        ok = pg.times(hours)
        every = _label_every(pg.js("document.getElementById('chart-body').clientWidth"))
        want = [ok[i] for i in range(0, len(hours), every)]
        got = [norm(e["text"]) for e in pg.ui("chart-x-label") if e["visible"]]
        return [] if got == want else [f"chart x labels {got}, expected {want} "
                                       "(Berlin CEST->CET at 01:00 UTC)"]
    finally:
        run.done(pg)
