"""The timed page reload: the rain page must re-fetch its data by itself.

The page schedules its next reload from the /api/schedule jobs (format.js
nextLoadDelay: the soonest next_run_utc wins, plus the after-refresh grace,
capped at the 60 s interval). This check fakes the schedule so the reload is
due a few seconds after the page's frozen "now", and gives /api/rain-
probability two answers (the real one, then a lower probability). Within
RELOAD_WAIT_S the page must request /api/rain-probability a second time on
its own and show the new number in the glance.
"""

from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone

from expect import LOCALES
from page import Run, norm

RELOAD_WAIT_S = 15  # the whole wait for the timed reload (the fault must lose inside it)
RELOAD_DELAY_S = 6  # the faked schedule makes the next reload due this many seconds after "now"
RAIN_PATH = "/api/rain-probability"


def _real_rain(base: str) -> dict:
    """The app's real /api/rain-probability answer (the first of the two faked ones)."""
    with urllib.request.urlopen(base + RAIN_PATH, timeout=10) as r:
        return json.loads(r.read() or "null")


def _schedule_fakes(run: Run, rain: dict) -> dict:
    """Fakes that make the next reload due RELOAD_DELAY_S after "now": the real rain
    answer, then the same with a lower probability (the reload must show it), and a
    /api/schedule whose radar job runs soon (it is the only job with a next_run_utc,
    so nextLoadDelay is next_run minus "now" plus the 10 s grace, capped at 60 s)."""
    now = datetime.fromisoformat(run.sc["now"].replace("Z", "+00:00")).astimezone(timezone.utc)
    rain2 = {**rain, "probability_pct": round(rain["probability_pct"] - 50)}
    run_at = (now - timedelta(seconds=RELOAD_DELAY_S - 10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    schedule = {"server_time_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "jobs": {"radar": {"interval_minutes": 5, "next_run_utc": run_at, "sources": ["radar"]},
                         "models": {"interval_minutes": 60, "next_run_utc": None, "sources": ["forecast"]}}}
    return {
        RAIN_PATH: [(200, json.dumps(rain)), (200, json.dumps(rain2))],
        "/api/schedule": [(200, json.dumps(schedule))],
    }


def reload_fires(run: Run) -> list[str]:
    """The rain page reloads by itself: after the faked schedule's short delay the
    page requests /api/rain-probability a second time (the glance still shows the
    real probability until then) and the new, lower number replaces it."""
    rain = _real_rain(run.base)
    if not isinstance(rain, dict) or "probability_pct" not in rain:
        return [f"the app's {RAIN_PATH} has no probability_pct, cannot fake a second answer"]
    new_pct = round(rain["probability_pct"] - 50)
    locale = LOCALES[run.lang]
    pg = run.page(fakes=_schedule_fakes(run, rain))
    try:
        first = [u for u in pg.p.requests if u.rsplit("?", 1)[0].endswith(RAIN_PATH)]
        want = pg.js(f"new Intl.NumberFormat({locale!r}, "
                     f"{{style: 'percent', maximumFractionDigits: 0}}).format({new_pct} / 100)")
        end = time.monotonic() + RELOAD_WAIT_S
        while time.monotonic() < end:
            pg.p.pump()
            urls = [u for u in pg.p.requests if u.rsplit("?", 1)[0].endswith(RAIN_PATH)]
            text = pg.js("document.getElementById('rain-probability').textContent || ''")
            if len(urls) > len(first) and norm(text) == want:
                break
            time.sleep(0.5)
        urls = [u for u in pg.p.requests if u.rsplit("?", 1)[0].endswith(RAIN_PATH)]
        text = pg.js("document.getElementById('rain-probability').textContent || ''")
        if len(urls) <= len(first):
            return [f"{RAIN_PATH} requested {len(urls)} times after page load, expected a second request "
                    f"within {RELOAD_WAIT_S} s: the timed page reload never fired "
                    f"(the faked schedule was due after {RELOAD_DELAY_S} s)"]
        if norm(text) != want:
            return [f"the page reloaded but the probability shows {text!r}, expected {want!r} "
                    "(the reload must show the new answer)"]
        return []
    finally:
        run.done(pg)
