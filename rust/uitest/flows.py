"""The flows over time: a refresh against bad data, the config retry, the theme
toggle and the wizard (setup, search, saving the location)."""

from __future__ import annotations

import re
import time

from expect import (CONFIG_RETRY_S, WIZARD_CITY, WIZARD_DETAIL, WIZARD_LABEL, WIZARD_RESULTS,
                    WIZARD_SELECTED)
from edges import (setup_texts_problems, wizard_cancel_problems, wizard_min_length_problems,
                   wizard_search_failed_problems)
from markup import markup_search
from page import Run, UIPage, expect_hidden, expect_text, expect_tokens, visible_one
from page_checks import theme_problems

def _page_errors(pg: UIPage) -> list[str]:
    pg.p.pump()
    return [e for e in pg.p.errors if e.startswith("exception:")]


def refresh_render_error(run: Run) -> list[str]:
    """Malformed data that today's renderers can't draw: the radar steps and an
    accuracy row are null. The other parts must still render, nothing may
    throw uncaught, and the next page reload must still be scheduled."""
    pg = run.page(fakes={
        "/api/radar/next-hour": [(200, '{"available": true, "steps": [null]}')],
        "/api/model-accuracy": [(200, '{"models": {"icon_d2": null}}')]})
    time.sleep(1.5)  # the countdowns tick once a second
    problems = [f"uncaught: {e}" for e in _page_errors(pg)]
    temp = pg.ui("now-temp")
    if not temp or not temp[0]["visible"] or not re.search(r"\d", temp[0]["text"]):
        problems.append("[data-test=now-temp] not shown: one part's bad data must not stop the others")
    if not any(e["rendered"] for e in pg.ui("chart-series")):
        problems.append("no [data-test=chart-series]: one part's bad data must not stop the others")
    page = pg.js("(document.querySelector('[data-test=countdown-page]') || {}).textContent || ''")
    m = re.search(r"(\d+):(\d{2})", page)
    if not m or int(m.group(1)) * 60 + int(m.group(2)) == 0:
        problems.append(f"[data-test=countdown-page] shows {page!r}: no page reload is scheduled")
    pg.close()
    return problems


def refresh_config_retry(run: Run) -> list[str]:
    """/api/config fails once at startup (503): the page must try again by
    itself and show the place and the forecast within CONFIG_RETRY_S."""
    pg = run.page(fakes={"/api/config": [(503, '{"detail": "unavailable"}')]})
    end = time.monotonic() + CONFIG_RETRY_S
    loc = ""
    while time.monotonic() < end:
        pg.p.pump()
        loc = pg.js("(document.querySelector('[data-test=location]') || {}).textContent || ''")
        temp = pg.js("(document.querySelector('[data-test=now-temp]') || {}).textContent || ''")
        if "52.520" in loc and re.search(r"\d", temp):
            break
        time.sleep(0.5)
    else:
        pg.close()
        return [f"/api/config failed once at startup; {CONFIG_RETRY_S} s later the place reads {loc!r} "
                "and the forecast is not shown: the page must retry by itself"]
    problems = [f"uncaught: {e}" for e in _page_errors(pg)]
    pg.close()
    return problems


def theme_toggle(run: Run) -> list[str]:
    """The theme toggle: a click flips light/dark and the choice survives a reload."""
    pg = run.page(scheme="dark")
    problems = theme_problems(pg.js("__ui.page()"), "dark")
    for step, want in (("first click", "light"), ("after reload", "light"), ("second click", "dark")):
        if step == "after reload":
            pg.reload()
        else:
            problems += pg.click("theme-toggle")
        lum = pg.js("__ui.page()")["bodyLum"] or 0
        if (want == "light") != (lum > 0.6):
            problems.append(f"system theme dark, {step}: expected the {want} theme, background luminance {lum:.2f}")
    run.done(pg)
    return problems


def lines_problems(pg: UIPage, hook: str, want: list[str]) -> list[str]:
    """The visible [data-test=hook] elements show want's texts, one rendered line per
    "\\n" (the place label is two lines, white-space: pre-line)."""
    got = pg.js(f"""[...document.querySelectorAll('[data-test="{hook}"]')].filter((e) => e.checkVisibility())
      .map((e) => {{ const r = document.createRange(); r.selectNodeContents(e);
        const tops = new Set([...r.getClientRects()].filter((x) => x.width > 0).map((x) => Math.round(x.top)));
        return {{ text: e.innerText, lines: tops.size }}; }})""")
    problems = [] if len(got) == len(want) else [f"{len(got)} visible [data-test={hook}], expected {len(want)}"]
    for i, (g, w) in enumerate(zip(got, want)):
        text = "\n".join(l.strip() for l in g["text"].strip().split("\n"))
        if text != w:
            problems.append(f"[data-test={hook}] #{i + 1} shows {g['text']!r}, expected {w!r}")
        elif g["lines"] != w.count("\n") + 1:
            problems.append(f"[data-test={hook}] #{i + 1} {w!r} takes {g['lines']} rendered lines, expected {w.count(chr(10)) + 1}")
    return problems


def run_wizard(run: Run):
    """The wizard: setup validation, the location search, saving, and changing it."""
    pg = run.page()
    run.add("setup-texts", setup_texts_problems(pg, run.lang))
    problems = []
    for hook, text in (("setup-lat", "91"), ("setup-lon", "13.4"), ("setup-tz", "Europe/Berlin")):
        problems += pg.type_into(hook, text)
    problems += pg.click("setup-save")
    el, p = visible_one(pg, "setup-status")
    problems += p
    if el and "90" not in el["text"]:
        problems.append(f"latitude 91: [data-test=setup-status] shows {el['text']!r}, expected the -90..90 range")
    if any("/api/location" in u for u in pg.p.requests):
        problems.append("latitude 91 was sent to /api/location; the page must reject it first")
    if el and run.lang == "de" and re.search(r"\blatitude\b", el["text"], re.I):
        problems.append(f"German page, English message: {el['text']!r}")
    run.add("validation", problems)
    run.shot(pg, "setup-validation")
    if "min-length" in run.names:
        run.add("min-length", wizard_min_length_problems(pg, run.lang))
    if "search-failed" in run.names:
        run.add("search-failed", wizard_search_failed_problems(run))
    if "markup-search" in run.names:  # the search result labels with HTML markup shown as text (markup.py)
        run.add("markup-search", markup_search(run))
    run.done(pg)
    if run.lang != "en":
        return
    pg = run.page()
    problems = pg.type_into("setup-search", "Alexanderplatz Berlin") + pg.click("setup-search-button")
    results = [e for e in pg.ui("setup-result") if e["visible"]]
    if len(results) < 3:
        problems.append(f"{len(results)} visible [data-test=setup-result] after the search, expected 3")
    else:
        problems += pg.click(selector='[data-test="setup-result"]')
        lat = (pg.ui("setup-lat") or [{}])[0].get("value") or ""
        lon = (pg.ui("setup-lon") or [{}])[0].get("value") or ""
        if not (lat.startswith("52.52") and lon.startswith("13.41")):
            problems.append(f"after picking the first result: latitude {lat!r}, longitude {lon!r}, expected 52.52…, 13.41…")
    run.add("search", problems)
    # each result is the two-line label; the status sentence joins the lines with ", "
    problems = lines_problems(pg, "setup-result", WIZARD_RESULTS)
    status = (pg.ui("setup-status") or [{}])[0].get("text") or ""
    raw = pg.js("document.querySelector('[data-test=\\'setup-status\\']')?.textContent || ''")
    if WIZARD_SELECTED not in status or "\n" in raw:
        problems.append(f"after picking: [data-test=setup-status] {raw!r}, expected {WIZARD_SELECTED!r} in one line")
    run.add("search-lines", problems)
    problems = pg.type_into("setup-tz", "Europe/Berlin") + pg.click("setup-save")
    end = time.monotonic() + 20
    while time.monotonic() < end and not any(e["visible"] for e in pg.ui("rain-answer")):
        time.sleep(0.2)
        pg.p.pump()
    problems += visible_one(pg, "rain-answer")[1] + expect_hidden(pg, "setup")
    problems += expect_text(pg, "location", WIZARD_CITY)  # the city only, not the street
    run.add("save", problems)
    run.shot(pg, "after-save")
    # the bar shows the city; the details page the saved label in full (wrapped, not cut off), coordinates below
    phone = run.page(width=360, height=740, query="?detailed")
    problems = expect_tokens(phone, "location", [WIZARD_CITY]) + expect_tokens(phone, "place-label", WIZARD_LABEL)
    problems += phone.js('__ui.clipped("place-label")') + expect_tokens(phone, "location-detail", WIZARD_DETAIL)
    info = phone.js("__ui.page()")
    if info["sw"] > 361:
        problems.append(f"page is {info['sw']} px wide at 360 px: {phone.js('__ui.overflowing()')}")
    run.add("location-long", problems)
    wide = run.page(query="?detailed")
    problems = [f"at 360 px: {p}" for p in lines_problems(phone, "place-label", ["\n".join(WIZARD_LABEL)])]
    problems += [f"at 1280 px: {p}" for p in lines_problems(wide, "place-label", ["\n".join(WIZARD_LABEL)])]
    run.done(wide)
    run.add("location-lines", problems)
    run.shot(phone, "after-save-phone-360")
    run.done(phone)
    problems = pg.click("location-button")
    problems += visible_one(pg, "setup")[1] + visible_one(pg, "setup-cancel")[1]
    if not problems:
        problems += pg.click("setup-cancel") + expect_hidden(pg, "setup") + visible_one(pg, "rain-answer")[1]
    run.add("change", problems)
    run.done(pg)
    if "cancel" in run.names:
        run.add("cancel", wizard_cancel_problems(run))
