"""The failed refresh: the parts keep their last good data and say so.

The page schedules its next reload from the faked /api/schedule (the
radar job runs DELAY_S seconds after the frozen "now", as in reload.py).
/api/now gets the app's real answer first, then a 500: on the second
refresh the Now tile must still show the first temperature and carry
the small outdated note ("Update failed - showing data from <time>");
the parts that fetched good again get no note.
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone

from page import Run, norm

WAIT_S = 15  # the whole wait for the timed reload and its failed /api/now
DELAY_S = 6  # the faked schedule makes the next reload due this many seconds after "now"
NOW_PATH = "/api/now"
NOTE_PREFIX = norm("Update failed \u2013 showing data from")  # the English note, a space and the time follow
TIME = r"\d{1,2}:\d{2}\s?[AP]M"  # the arrival time, en-US minute precision ("12:50 PM")


def _now_requests(pg) -> list[str]:
    """The /api/now requests the page made so far (query strings stripped)."""
    return [u for u in pg.p.requests if u.rsplit("?", 1)[0].endswith(NOW_PATH)]


def _real_now(base: str) -> dict | None:
    """The app's real /api/now answer (the first of the two faked ones), or None."""
    with urllib.request.urlopen(base + NOW_PATH, timeout=10) as r:
        return json.loads(r.read() or "null")


def _now_temp(pg) -> tuple[bool, str]:
    """The Now tile's temperature: (visible, normalized text)."""
    els = pg.ui("now-temp")
    if not els:
        return (False, "")
    return (bool(els[0]["visible"]), norm(els[0]["text"]))


def _fakes(run: Run, now: dict) -> dict:
    """The faked answers: the real /api/now answer, then the 500 the second
    refresh must fall back from, and the /api/schedule whose radar job makes
    the page reload due DELAY_S seconds after the frozen "now"."""
    at = datetime.fromisoformat(run.sc["now"].replace("Z", "+00:00")).astimezone(timezone.utc)
    run_at = (at - timedelta(seconds=DELAY_S - 10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    schedule = {"server_time_utc": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "jobs": {"radar": {"interval_minutes": 5, "next_run_utc": run_at, "sources": ["radar"]},
                         "models": {"interval_minutes": 60, "next_run_utc": None, "sources": ["forecast"]}}}
    return {NOW_PATH: [(200, json.dumps(now)), (500, '{"detail": "unavailable"}')],
            "/api/schedule": [(200, json.dumps(schedule))]}


def refresh_keeps_old(run: Run) -> list[str]:
    """The failed refresh keeps the last good data: the Now tile still shows
    the first temperature and gains the outdated note with the arrival time;
    the parts that fetched good again get no note."""
    now = _real_now(run.base)
    if not isinstance(now, dict) or not (now.get("available") and now.get("conditions")):
        return [f"the app's {NOW_PATH} has no usable observation, cannot fake a failing second answer"]
    pg = run.page(fakes=_fakes(run, now))
    try:
        temp_vis, temp = _now_temp(pg)
        if not temp_vis or not temp:
            return [f"the Now tile has no visible temperature after the real load ({temp!r}), cannot compare"]
        first = len(_now_requests(pg))
        end = time.monotonic() + WAIT_S
        while time.monotonic() < end:
            pg.p.pump()
            if len(_now_requests(pg)) > first:
                break
            time.sleep(0.5)
        if len(_now_requests(pg)) <= first:
            return [f"{NOW_PATH} requested {first} times after page load, expected a second request "
                    f"within {WAIT_S} s: the timed page reload never fired "
                    f"(the faked schedule was due after {DELAY_S} s)"]
        notes = []
        end = time.monotonic() + WAIT_S
        while time.monotonic() < end:
            pg.p.pump()
            notes = [e for e in pg.ui("outdated")
                     if e["attrs"].get("data-part") == "now" and e["visible"]]
            if notes:
                break
            time.sleep(0.2)
        problems = []
        if not notes:
            problems.append("[data-test=outdated][data-part=now] not shown after the failed refresh: "
                            "the Now part must keep its last good data and note it as outdated")
        else:
            if not re.fullmatch(NOTE_PREFIX + " " + TIME, norm(notes[0]["text"])):
                problems.append(f"[data-test=outdated][data-part=now] shows {notes[0]['text']!r}, "
                                f"expected {NOTE_PREFIX!r} plus an arrival time like {TIME!r}")
        temp2_vis, temp2 = _now_temp(pg)
        if not temp2_vis or temp2 != temp:
            problems.append("the Now tile lost its temperature on the failed refresh: the last good "
                            f"data must stay ({temp!r}, visible={temp_vis} became {temp2!r}, visible={temp2_vis})")
        for e in pg.ui("outdated"):
            if e["attrs"].get("data-part") != "now" and e["visible"]:
                problems.append(f"[data-test=outdated][data-part={e['attrs'].get('data-part')}] is shown "
                                f"({e['text']!r}) although its endpoints fetched good again")
        return problems
    finally:
        pg.close()
