"""The text checks the page checks leave out: the Now card's title and dt
labels (no data-test on the labels), the radar's not-available line, the
fallback note's wording, the setup form's save button, and the wizard's edge
paths (a search under 3 characters, a failed search, canceling a change)."""

from __future__ import annotations

import json
import time

from expect import (NOW_FALLBACK, NOW_FALLBACK_NAME, NOW_LABELS, NOW_TITLE, RADAR_UNAVAILABLE,
                    REPORT_NIGHT_NOW, REPORT_NIGHT_OBSERVED, REPORT_TEXT, SCENE_LABEL, SETUP_SAVE,
                    WIZARD_MIN_LENGTH, WIZARD_SEARCH_FAILED)
from page import Run, UIPage, expect_hidden, expect_text, expect_tokens, has, norm, visible_one


def now_texts_problems(pg: UIPage, lang: str) -> list[str]:
    """The Now card's title and its dt labels, word for word (the values are
    checked by the now-* checks)."""
    problems = []
    title = pg.js("document.getElementById('now-title')?.textContent || ''")
    if norm(title) != norm(NOW_TITLE[lang]):
        problems.append(f"#now-title shows {norm(title)!r}, expected {NOW_TITLE[lang]!r}")
    labels = pg.js("[...document.querySelectorAll('.now-grid dt')].map((d) => d.textContent)")
    want = [norm(x) for x in NOW_LABELS[lang]]
    if len(labels) != len(want):
        return problems + [f"{len(labels)} labels in .now-grid, expected {len(want)}: {labels}"]
    for i, (got, w) in enumerate(zip(labels, want)):
        if norm(got) != w:
            problems.append(f".now-grid label {i + 1} shows {norm(got)!r}, expected {w!r}")
    return problems


def radar_unavailable_text_problems(pg: UIPage, lang: str) -> list[str]:
    """The radar card's 'not available' line, word for word (its visibility is
    checked by the radar-unavailable check)."""
    return expect_text(pg, "radar-unavailable", RADAR_UNAVAILABLE[lang])


def fallback_text_problems(pg: UIPage, lang: str) -> list[str]:
    """The fallback note on the cloud cover value: the wording with the
    station's name (the mark's presence is checked by the now-fallback check)."""
    marks = [e for e in pg.ui("now-fallback") if e["visible"]]
    if len(marks) != 1:
        return [f"{len(marks)} visible [data-test=now-fallback], expected 1"]
    want = NOW_FALLBACK[lang].replace("{name}", NOW_FALLBACK_NAME)
    return ([f"[data-test=now-fallback] shows {norm(marks[0]['text'])!r}, expected {want!r}"]
            if norm(marks[0]["text"]) != norm(want) else [])


def setup_texts_problems(pg: UIPage, lang: str) -> list[str]:
    """The setup form's save button, word for word (the form's presence is
    checked by the setup-visible check)."""
    return expect_text(pg, "setup-save", SETUP_SAVE[lang])


# which of the sky's sun/moon/stars the page shows (display + visibility)
NIGHT_PARTS = """(() => {
  const vis = (sel) => { const el = document.querySelector(sel);
    return !!el && el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true}); };
  return {sun: vis('.sky-sun'), moon: vis('.sky-moon'), stars: vis('.sky-stars')};
})()"""


def report_night_problems(pg: UIPage, lang: str, rep: dict) -> list[str]:
    """The scene the page shows for a fresh report observed after the
    place's sunset: <html data-scene> is the clear night scene, the sky
    shows the night picture (moon and stars, no sun), and the front's
    report line names the report. The planted fault (isDayAt always
    answering day) flips data-scene to clear-day and brings the sun back."""
    problems = []
    got = pg.js("document.documentElement.getAttribute('data-scene')")
    if got != "clear-night":
        problems.append(f"data-scene {got!r} with a fresh clear report observed {rep['observed_at']}, "
                        "expected 'clear-night' (after the place's sunset)")
    parts = pg.js(NIGHT_PARTS)
    if parts.get("sun"):
        problems.append("the sun is shown although the report's scene is the clear night one")
    for part in ("moon", "stars"):
        if not parts.get(part):
            problems.append(f"the {part} are not shown although the report's scene is the clear night one")
    i = 0 if lang == "en" else 1
    want = REPORT_TEXT["line"][lang].format(scene=SCENE_LABEL["clear-night"][i],
                                            time=pg.times([rep["observed_at"]])[0])
    lines = pg.js("""[...document.querySelectorAll('[data-report-host] [data-test="report-line"]')]
        .filter((el) => el.checkVisibility({checkOpacity: true}) && !el.closest('[inert]'))
        .map((el) => el.textContent)""")
    if len(lines) != 1:
        problems.append(f"{len(lines)} visible [data-test=report-line], expected 1 ({want!r})")
    elif not has(lines[0], want):
        problems.append(f"[data-test=report-line] shows {norm(lines[0])!r}, expected {want!r}")
    return problems


def _wizard_status_problems(pg: UIPage, want: str) -> list[str]:
    """[data-test=setup-status] shows want and carries the error class (the
    page marks a bad status line with the .error style)."""
    problems = expect_text(pg, "setup-status", want)
    error = pg.js("(document.querySelector('[data-test=\\'setup-status\\']') || {}).classList.contains('error')")
    if not error:
        problems.append(f"[data-test=setup-status] shows {want!r} without its error state")
    return problems


def wizard_min_length_problems(pg: UIPage, lang: str) -> list[str]:
    """The wizard rejects a search under 3 characters before any request: the
    status line shows the min-length message from i18n.js for the language, in
    its error state, and no /api/geocode request was sent."""
    problems = pg.type_into("setup-search", "ab") + pg.click("setup-search-button")
    problems += _wizard_status_problems(pg, WIZARD_MIN_LENGTH[lang])
    if any("/api/geocode" in u for u in pg.p.requests):
        problems.append("a 2-character search was sent to /api/geocode; the page must reject it first")
    return problems


def wizard_search_failed_problems(run: Run) -> list[str]:
    """A failed search (/api/geocode answers 500) must not go silent: the
    status line shows the 'search failed' message from i18n.js for the
    language, in its error state (the planted fault removes the status call)."""
    pg = run.page(fakes={"/api/geocode": [(500, '{"detail": "no results"}')]})
    problems = pg.type_into("setup-search", "Alexanderplatz Berlin") + pg.click("setup-search-button")
    for _ in range(25):
        text = (pg.ui("setup-status") or [{}])[0].get("text") or ""
        if any(k in text for k in ("again", "noch")):
            break
        pg.p.pump()
        time.sleep(0.2)
    problems += _wizard_status_problems(pg, WIZARD_SEARCH_FAILED[run.lang])
    pg.close()  # not run.done: the 500 is the point, its log must not reach the console check
    return problems


def wizard_cancel_problems(run: Run) -> list[str]:
    """In change mode (the wizard opened from the location button) the cancel
    button hides the wizard without saving: no new POST /api/location request,
    the dashboard (rain-answer) and the place label are unchanged."""
    pg = run.page()
    place = (pg.ui("location") or [{}])[0].get("text") or ""
    before = [u for u in pg.p.requests if "/api/location" in u]
    problems = pg.click("location-button")
    problems += visible_one(pg, "setup")[1] + visible_one(pg, "setup-cancel")[1]
    if not problems:
        problems += pg.click("setup-cancel")
        problems += expect_hidden(pg, "setup")
        problems += visible_one(pg, "rain-answer")[1]
        problems += expect_tokens(pg, "location", [place])
        sent = [u for u in pg.p.requests if "/api/location" in u]
        if len(sent) != len(before):
            problems.append(f"{len(sent) - len(before)} request(s) to /api/location after cancel: cancel must not save")
    run.shot(pg, "after-cancel")
    run.done(pg)
    return problems


def report_night(run: Run) -> None:
    """A fresh "clear" report observed after the place's sunset (the page
    at 19:30Z, the report at 19:25Z, both past Berlin's sunset of
    2026-09-30) must show the clear night scene (report-night)."""
    rep = {"id": 90, "kind": "clear", "intensity": None, "confirms": False,
           "observed_at": REPORT_NIGHT_OBSERVED}
    pg = run.page(now=REPORT_NIGHT_NOW,
                  fakes={"/api/reports/current": [(200, json.dumps({"report": rep}))] * 8})
    run.add("report-night", report_night_problems(pg, run.lang, rep))
    run.done(pg)
