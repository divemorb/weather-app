"""The checks on the details page (?detailed): the Details card open right
under the top bar, then its content (weights, signals, countdowns, data
sources, the observation stations, the accuracy table)."""

from __future__ import annotations

import re

from expect import ACCURACY_HEAD, FIXED, MODEL_LABELS, SOURCE_KIND, SOURCES, WEIGHTS
from page import (UIPage, expect_hidden, expect_text, expect_tokens, has, norm,
                  observation_station_problems, station_map_problems, visible_one)
from stations_ui import stations_explained_problems


DETAILS_OPEN = """(() => {
  const d = document.querySelector('[data-test="details"]');
  if (!d) return null;
  const shown = (e) => !!e && e.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true });
  const toggles = [...d.querySelectorAll('summary')].filter(shown).length;
  const heads = [...d.querySelectorAll('h1, h2, h3')].filter((h) => shown(h) && h.closest('[data-test="details"]') === d
    && h.textContent.trim() === 'Details' && !h.closest('summary'));
  const top = document.querySelector('.topbar');
  return { tag: d.tagName.toLowerCase(), open: d.tagName === 'DETAILS' ? d.open : true, toggles, heads: heads.length,
           gap: top ? d.getBoundingClientRect().top - top.getBoundingClientRect().bottom : null };
})()"""


def details_open_problems(pg: UIPage) -> list[str]:
    """The details page shows the Details card open, not collapsible (no visible
    <summary>), under a plain "Details" heading, right under the top bar."""
    det, problems = visible_one(pg, "details")
    d = pg.js(DETAILS_OPEN)
    if det and d:
        if not d["open"]:
            problems.append(f"[data-test=details] is a closed <{d['tag']}>, expected open")
        if d["toggles"]:
            problems.append(f"{d['toggles']} visible <summary> in [data-test=details]: the card is not collapsible")
        if d["heads"] != 1:
            problems.append(f"{d['heads']} visible <h1>-<h3> 'Details' heading(s) in the card, expected 1")
        if d["gap"] is not None and not -1 <= d["gap"] <= 48:
            problems.append(f"the card starts {d['gap']:.0f} px below the top bar, expected right under it (0-48 px)")
    if not any(e["visible"] for e in pg.ui("source-row")):
        problems.append("no visible [data-test=source-row]: the card's content shows without a click")
    return problems


def check_details(pg: UIPage, sc: str, exp: dict, names: list[str], add):
    """On the details page (?detailed)."""
    lang = pg.lang
    add("details-open", details_open_problems(pg))
    pg.js("__ui.openDetails()")  # today's page: open the card to check its content
    pg.settle()
    if "details-weights" in names:
        add("details-weights", expect_tokens(pg, "details-weights", WEIGHTS[lang]))
    if "details-signals" in names:
        add("details-signals", expect_tokens(pg, "details-signals", exp["signals"][lang]))
    if "details-weighting" in names:  # only while the API says accuracy_weighted
        add("details-weighting", expect_text(pg, "details-weighting", FIXED["signals.accuracy-weighted"][lang])
            if exp.get("accuracy_weighted") else expect_hidden(pg, "details-weighting"))
    for job in ("radar", "models", "page"):
        hook = f"countdown-{job}"
        if hook in names:
            el, problems = visible_one(pg, hook)
            if el and not re.search(r"\d+:\d{2}", el["text"]):
                problems.append(f"[data-test={hook}] shows {el['text']!r}, expected a countdown like 4:59")
            add(hook, problems)
    if "source-rows" in names:
        rows = [e for e in pg.ui("source-row") if e["visible"]]
        got = [e["attrs"].get("data-source") for e in rows]
        problems = [] if sorted(got) == sorted(SOURCES) else [f"[data-test=source-row] data-source: {got}, expected {list(SOURCES)}"]
        for e in rows:
            key = e["attrs"].get("data-source")
            for want in (SOURCES.get(key, ""), SOURCE_KIND.get(key, {}).get(lang, "")):
                if want and not has(e["text"], want):
                    problems.append(f"source row {key}: {e['text']!r} lacks {want!r}")
        add("source-rows", problems)
    if "source-errors" in names:
        n = sum(e["visible"] for e in pg.ui("source-error"))
        want = exp.get("source_errors", 0)
        add("source-errors", [] if n == want else [f"{n} visible [data-test=source-error], expected {want}"])
    if "observation-stations" in names:
        add("observation-stations", observation_station_problems(pg))
    if "station-map" in names:
        add("station-map", station_map_problems(pg, exp))
    if "stations-explained" in names:  # what the stations are for, where they are (stations_ui.py)
        add("stations-explained", stations_explained_problems(pg))
    add("details-fit", pg.js('__ui.sticksOut("details")'))
    if "accuracy-table" in names:
        add("accuracy-table", accuracy_problems(pg, exp))
    if "accuracy-head" in names:
        add("accuracy-head", expect_tokens(pg, "accuracy-head", ACCURACY_HEAD[pg.lang]))
    if "accuracy-note" in names:  # the fixture has rain hours, so the no-rain note stays hidden
        add("accuracy-note", expect_text(pg, "accuracy-note", FIXED["accuracy.note"][pg.lang])
            + expect_hidden(pg, "accuracy-no-rain"))


def accuracy_problems(pg, exp) -> list[str]:
    """The accuracy table: one row per model, best accuracy first, with the expected tokens."""
    lang = pg.lang
    rows = [e for e in pg.ui("accuracy-row") if e["visible"]]
    if exp.get("accuracy") is None:
        problems = expect_tokens(pg, "accuracy-status", [])
        el = next((e for e in pg.ui("accuracy-status") if e["visible"]), None)
        if el and norm(FIXED["accuracy.none"][lang]) not in norm(el["text"]):
            problems.append(f"[data-test=accuracy-status] shows {el['text']!r}, expected {FIXED['accuracy.none'][lang]!r}")
        if rows:
            problems.append(f"{len(rows)} visible [data-test=accuracy-row] without data")
        return problems
    problems = expect_hidden(pg, "accuracy-status")
    order = [e["attrs"].get("data-model") for e in rows]
    want = [m for m, *_ in exp["accuracy"]]
    if order != want:
        return problems + [f"[data-test=accuracy-row] data-model order {order}, expected {want} (best event accuracy first)"]
    for e, (model, pct_en, pct_de, mae_en, mae_de) in zip(rows, exp["accuracy"]):
        tokens = [MODEL_LABELS[model], pct_en if lang == "en" else pct_de]
        mae = mae_en if lang == "en" else mae_de
        if mae:
            tokens.append(mae)
        missing = [t for t in tokens if not has(e["text"], t)]
        if missing:
            problems.append(f"accuracy row {model}: {e['text']!r} lacks {missing}")
    return problems
