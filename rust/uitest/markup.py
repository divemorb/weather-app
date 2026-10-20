"""Upstream text must be shown as text: faked API answers whose texts carry
HTML markup must reach the page as literal text (textContent, never
innerHTML), so the markup never becomes elements (CSP alone would block the
onerror, not the parsed elements); markup_api covers the rain page (place,
station, fallback, observation names), markup_search the wizard's results.
"""

from __future__ import annotations

import json
import time

from clock import api_answer
from page import Run

MARK = '<img src=x onerror="window.__xss=1"><i data-xss>Mark</i> & Co'


def api_markup_fakes(run: Run) -> dict:
    """The app's real answers of /api/config, /api/now and /api/model-accuracy
    with the markup planted in every name the page fills (the location's
    label, the station's name, the fallback's name, the observation names)."""
    fakes = {}
    for path in ("/api/config", "/api/now", "/api/model-accuracy"):
        status, body = api_answer(run.base, path)
        if status != 200 or body is None:
            continue
        if path == "/api/config":
            body["location"]["label"] = MARK
        elif path == "/api/now":
            body["conditions"]["station"]["name"] = MARK
            body["conditions"]["fallback"] = {"temperature_c": {"name": MARK}}
        else:
            for entry in body["stations"]:
                entry["name"] = MARK
        fakes[path] = [(200, json.dumps(body))] * 6
    return fakes


def _xss_problems(pg) -> list[str]:
    """Problems when the markup became HTML: every [data-xss] element on the page."""
    n = pg.js("document.querySelectorAll('[data-xss]').length")
    return [] if n == 0 else [f"API text became HTML: {n} element(s) [data-xss] on the page"]


def markup_api(run: Run) -> list[str]:
    """The rain page with markup in the API texts: the place label, the Now
    station, the fallback note and the observation-station names must show the
    markup as literal text, and no [data-xss] element may exist (rain/en)."""
    pg = run.page(fakes=api_markup_fakes(run))
    try:
        pg.js("__ui.openDetails()")
        pg.settle()
        problems = []
        for hook in ("location", "now-station", "now-fallback", "observation-station"):
            texts = [e.get("text") or "" for e in pg.ui(hook)][:3]
            if not any(MARK in text for text in texts):
                problems.append(f"[data-test={hook}] does not show the API text as text: {texts}")
        return problems + _xss_problems(pg)
    finally:
        run.done(pg)


def markup_search(run: Run) -> list[str]:
    """The wizard's search with markup in the result labels: the first result
    must show the label as literal text, and no [data-xss] element may exist
    (wizard/en)."""
    pg = run.page(fakes={"/api/geocode": [(200, json.dumps({"results": [
        {"label": MARK + "\nBerlin", "latitude": 52.52, "longitude": 13.405},
        {"label": "Mitte\nBerlin", "latitude": 52.52, "longitude": 13.4},
    ]}))]})
    try:
        problems = pg.type_into("setup-search", "Alexanderplatz Berlin") + pg.click("setup-search-button")
        for _ in range(25):
            results = [e for e in pg.ui("setup-result") if e["visible"]]
            if results:
                break
            pg.p.pump()
            time.sleep(0.2)
        if not results:
            return problems + ["no visible [data-test=setup-result] after the search"]
        if MARK not in (results[0].get("text") or ""):
            problems.append(f"[data-test=setup-result] #1 does not show the API text as text: {results[0].get('text')!r}")
        return problems + _xss_problems(pg)
    finally:
        run.done(pg)
