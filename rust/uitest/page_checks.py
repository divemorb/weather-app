"""The checks that run on one loaded page: the common content, the radar, the
chart, the details card, the kiosk view."""

from __future__ import annotations

import calendar
import json
import math
import re
import time

from expect import (ACCURACY_HEAD, ANSWER, ATTRIBUTION_LINKS, CONTRAST_MOMENTS, CONTRAST_PCT,
                    FIXED, MODEL_LABELS, NOW, RADAR_CAPTION, SOURCE_KIND, SOURCES,
                    WEIGHTS, WHEN)
from page import (Run, UIPage, expect_hidden, expect_text, expect_tokens, fmt_mm, has, norm,
                  observation_station_problems, station_map_problems, visible_one)
from stations_ui import stations_explained_problems


def page_unconfigured(run: Run):
    """The unconfigured scenario: the setup form on the big view (A, light)."""
    pg = run.page()
    info = pg.js("__ui.page()")
    run.add("lang", [] if info["lang"] == run.lang else
            [f'<html lang="{info["lang"]}">, expected "{run.lang}"'])
    problems = [p for hook in ("setup", "setup-search", "setup-lat", "setup-lon", "setup-tz", "setup-save")
                for p in visible_one(pg, hook)[1]]
    run.add("setup-visible", problems + expect_hidden(pg, "rain-answer"))
    run.add("theme-light", theme_problems(info, "light"))
    run.icons["light"] = pg.js('__ui.icons("theme-toggle")')
    run.add("contrast-light", contrast_problems(pg))
    run.add("buttons", pg.js("__ui.controls()"))
    run.shot(pg, "desktop-light")
    run.done(pg)


# --- checks on one loaded page -------------------------------------------------

def check_common_a(pg: UIPage, sc: str, exp: dict, add):
    """Desktop, light theme: content checks."""
    lang = pg.lang
    info = pg.js("__ui.page()")
    add("lang", [] if info["lang"] == lang else [f'<html lang="{info["lang"]}">, expected "{lang}"'])
    if "location" in exp:
        add("location", expect_tokens(pg, "location", exp["location"]))
    add("theme-light", theme_problems(info, "light"))
    add("contrast-light", contrast_problems(pg))
    add("buttons", pg.js("__ui.controls()"))
    el, problems = visible_one(pg, "attribution")
    if el:
        missing = [d for d in ATTRIBUTION_LINKS if not any(d in href for href in el["links"])]
        if missing:
            problems.append(f"[data-test=attribution] has no link to {missing}")
    add("attribution", problems)


def theme_problems(info, theme) -> list[str]:
    """Problems if the page background isn't opaque or matches the theme's luminance."""
    if not info["bodyBgOpaque"]:
        return ["no opaque background colour on body/html (set one per theme)"]
    lum = info["bodyLum"]
    if theme == "light" and lum < 0.6:
        return [f"system theme light, but the page background is {info['bodyBg']} (luminance {lum:.2f} < 0.6)"]
    if theme == "dark" and lum > 0.2:
        return [f"system theme dark, but the page background is {info['bodyBg']} (luminance {lum:.2f} > 0.2)"]
    return []


def theme_icon_problems(icons: dict) -> list[str]:
    """The theme toggle shows one icon at a time, and a different one per theme."""
    problems = [f"{theme} theme: [data-test=theme-toggle] shows {len(shown)} icons {shown}, expected exactly one"
                for theme, shown in icons.items() if len(shown) != 1]
    if not problems and icons.get("light") == icons.get("dark"):
        problems.append(f"[data-test=theme-toggle] shows the same icon in both themes: {icons['light']}")
    return problems


def seek_cycle(pg, phase: float):
    """Pause every animation and seek it to `phase` of its own cycle (moment m of
    the contrast check, phase m / CONTRAST_MOMENTS: each cycle is a different
    length, so phases spread over the whole sky state, not one time window).
    Leaves the animations paused: only for pages closed right after."""
    pg.js(f"__ui.seekCycle({phase!r})")


def contrast_problems(pg) -> list[str]:
    """WCAG AA for every visible text against the pixels drawn behind it (the text
    made transparent for the screenshot), so translucent tiles over a moving sky
    count as they look: CONTRAST_MOMENTS moments, scrolled through the page; per
    text the worst moment counts, and within it the CONTRAST_PCT worst pixels may
    be below (a raindrop crossing a word). The moments are seeked, not waited for:
    every animation is paused at a fixed phase of its own cycle."""
    worst: dict[str, dict] = {}
    for m in range(CONTRAST_MOMENTS):
        seek_cycle(pg, m / CONTRAST_MOMENTS)
        info = pg.js("__ui.page()")
        vh, sh = info["ih"], info["sh"]
        tops = list(range(0, max(sh - vh, 0) + 1, max(vh - 40, 100)))
        if tops[-1] < sh - vh:
            tops.append(sh - vh)
        for top in tops:
            pg.js(f"window.scrollTo(0, {top})")
            pg.frame()
            items = [dict(it, rects=[r for r in it["rects"] if r["y"] >= 0 and r["y"] + r["h"] <= vh])
                     for it in pg.js("__ui.textItems()")]
            items = [it for it in items if it["rects"]]
            if not items:
                continue
            pg.js("__ui.hideText(true)")
            pg.frame()
            b64 = pg.shot_b64()
            pg.js("__ui.hideText(false)")
            for r in pg.js(f"__ui.pixelContrast({json.dumps(b64)}, {json.dumps(items)}, 0, {CONTRAST_PCT})"):
                if r["label"] not in worst or r["ratio"] < worst[r["label"]]["ratio"]:
                    worst[r["label"]] = dict(r, moment=m)
    pg.js("window.scrollTo(0, 0)")
    if not worst:
        return ["no visible text found"]
    return [f"{label}: {r['ratio']:.2f}:1 < {r['need']}:1 (moment {r['moment'] + 1}), text {r['fg']} on {r['bg']}"
            for label, r in sorted(worst.items(), key=lambda kv: kv[1]["ratio"] / kv[1]["need"])
            if r["ratio"] + 1e-6 < r["need"]]


def check_glance(pg: UIPage, exp: dict, add):
    """The glance card: the rain answer, when, and the probability (or its placeholder)."""
    lang = pg.lang
    add("rain-answer", expect_text(pg, "rain-answer", ANSWER[exp["answer"]][lang]))
    if exp["when"]:
        add("rain-when", expect_text(pg, "rain-when", WHEN[exp["when"]][lang]))
    else:
        shown = [e for e in pg.ui("rain-when") if e["visible"] and e["text"]]
        add("rain-when", [f"[data-test=rain-when] shows {shown[0]['text']!r} without data"] if shown else [])
    if exp["probability"]:
        add("rain-probability", expect_tokens(pg, "rain-probability", [exp["probability"][lang]]))
    else:
        shown = [e for e in pg.ui("rain-probability") if e["visible"] and re.search(r"\d", e["text"])]
        add("rain-probability", [f"[data-test=rain-probability] shows a number without data: {shown[0]['text']!r}"]
            if shown else [])
        # a placeholder (e.g. "—") is not rain: no accent colour, a neutral grey or the text colour
        placeholder = [e for e in pg.ui("rain-probability") if e["visible"] and e["text"]]
        col = pg.js('__ui.textColor("rain-probability")')
        if placeholder and col and col["sat"] > 0.25:
            add("rain-probability", [f"[data-test=rain-probability] shows the no-data placeholder "
                                     f"{placeholder[0]['text']!r} in {col['hex']} (a colour, HSL saturation "
                                     f"{col['sat']:.2f}); without data it must be neutral (text or muted colour, "
                                     "saturation <= 0.25): the accent colour means rain"])


def check_radar(pg: UIPage, exp: dict, add):
    """The radar card: the steps, the labels, the caption, and the max or the dry sentence."""
    lang = pg.lang
    steps = [e for e in pg.ui("radar-step") if e["visible"]]
    n = len(exp["radar"])
    start = exp["radar_start"]
    isos = [time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(_epoch(start) + 300 * i)) for i in range(n + 1)]
    labels_ok = pg.times(isos)  # the n step starts and the end of the hour
    problems = []
    if len(steps) != n:
        problems.append(f"{len(steps)} visible [data-test=radar-step], expected {n}")
    else:
        for i, (el, mm) in enumerate(zip(steps, exp["radar"])):
            want_rain = "1" if mm > 0 else "0"
            if el["attrs"].get("data-rain") != want_rain:
                problems.append(f"step {i} ({labels_ok[i]}): data-rain={el['attrs'].get('data-rain')!r}, expected {want_rain!r}")
            label = el["attrs"].get("aria-label", "")
            for token in (labels_ok[i], fmt_mm(mm, lang)):
                if not has(label, token):
                    problems.append(f"step {i}: aria-label {label!r} lacks {token!r}")
    add("radar-steps", problems[:8])
    labels = [norm(e["text"]) for e in pg.ui("radar-label") if e["visible"]]
    problems = []
    if len(labels) < 3:
        problems.append(f"{len(labels)} visible [data-test=radar-label], expected at least 3: {labels}")
    else:
        unknown = [t for t in labels if t not in labels_ok]
        if unknown:
            problems.append(f"labels {unknown} are not step times (allowed: {labels_ok})")
        else:
            idx = [labels_ok.index(t) for t in labels]
            if idx != sorted(set(idx)):
                problems.append(f"labels not distinct and in time order: {labels}")
            if labels[0] != labels_ok[0]:
                problems.append(f"first label {labels[0]!r}, expected the first step's time {labels_ok[0]!r}")
    add("radar-labels", problems)
    add("radar-caption", expect_text(pg, "radar-caption", RADAR_CAPTION[lang]))
    peak = max(exp["radar"])
    if peak > 0:  # rain: the amount of the tallest step, once; no "dry" sentence
        shown = [e for e in pg.ui("radar-max") if e["visible"]]
        want = fmt_mm(peak, lang)
        problems = [] if len(shown) == 1 else [
            f"{len(shown)} visible [data-test=radar-max], expected one (the amount at the tallest step)"]
        problems += [f"[data-test=radar-max] shows {e['text']!r}, expected {want!r}"
                     for e in shown if not has(e["text"], want)]
        add("radar-max", problems)
        add("radar-dry", expect_hidden(pg, "radar-dry"))
    else:  # dry: the sentence instead of an amount (the empty tracks stay)
        add("radar-dry", expect_text(pg, "radar-dry", FIXED["radar.dry"][lang]))
        add("radar-max", expect_hidden(pg, "radar-max"))


def _epoch(iso: str) -> int:
    return calendar.timegm(time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ"))


def check_now(pg: UIPage, add):
    """The Now card: every value shows its expected token in the page's language."""
    for hook, tokens in NOW.items():
        add(hook, expect_tokens(pg, hook, tokens[pg.lang]))


def check_chart(pg: UIPage, exp: dict, add):
    """The 24-hour chart: the SVG, the series, the legend, the axis labels, and the unit."""
    lang = pg.lang
    if exp["chart"] == "unavailable":
        add("chart-unavailable", expect_text(pg, "chart-unavailable", FIXED["chart.unavailable"][lang])
            + [f"{n} rendered [data-test=chart-series] without data" for n in
               [sum(e["rendered"] for e in pg.ui("chart-series"))] if n])
        return
    if exp["chart"] == "dry":
        add("chart-dry", expect_text(pg, "chart-dry", FIXED["chart.dry"][lang]))
        return
    add("chart-dry", expect_hidden(pg, "chart-dry"))
    svg, problems = visible_one(pg, "chart")
    if svg and svg["tag"] != "svg":
        problems.append(f"[data-test=chart] is a <{svg['tag']}>, expected an inline <svg>")
    if svg and not svg["attrs"].get("aria-label") and svg["attrs"].get("role") != "img":
        problems.append('[data-test=chart] needs role="img" and an aria-label')
    add("chart-svg", problems)
    series = [e["attrs"].get("data-model") for e in pg.ui("chart-series") if e["rendered"]]
    add("chart-series", [] if series == exp["models"] else
        [f"rendered [data-test=chart-series] data-model: {series}, expected {exp['models']} (API order)"])
    legend = [norm(e["text"]) for e in pg.ui("chart-legend-item") if e["visible"]]
    want = [MODEL_LABELS[m] for m in exp["models"]]
    add("chart-legend", [] if legend == want else [f"legend {legend}, expected {want}"])
    ys = [norm(e["text"]) for e in pg.ui("chart-y-label") if e["visible"]]
    want_y = exp["y_labels"]
    add("chart-y-labels", [] if sorted(ys, key=_num) == want_y else [f"y labels {ys}, expected {want_y} (niceScale)"])
    hours = [time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(_epoch(exp["hours_start"]) + 3600 * i)) for i in range(25)]
    ok = pg.times(hours)
    xs = [norm(e["text"]) for e in pg.ui("chart-x-label") if e["visible"]]
    problems = []
    if len(xs) < 4:
        problems.append(f"{len(xs)} visible [data-test=chart-x-label], expected at least 4: {xs}")
    elif any(x not in ok for x in xs):
        problems.append(f"x labels {xs} are not hour times (allowed: {ok[:6]}…)")
    else:
        idx = [ok.index(x) for x in xs]
        if idx != sorted(set(idx)):
            problems.append(f"x labels not distinct and in time order: {xs}")
    add("chart-x-labels", problems)
    add("chart-unit", expect_tokens(pg, "chart-unit", ["mm"]))


def _num(s: str) -> float:
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return float("inf")


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


# The cards' content must stay inside the cards: for each of the three cards, the first
# element that reaches outside its box (1 px tolerance; zero-sized or hidden elements
# don't count), one string per such card.
CONTAINED_JS = """(() => {
  const out = [];
  for (const id of ["glance", "now", "chart-card"]) {
    const c = document.getElementById(id);
    if (!c || !c.checkVisibility()) continue;
    const r = c.getBoundingClientRect();
    for (const el of c.querySelectorAll("*")) {
      if (getComputedStyle(el).visibility === "hidden") continue;
      const b = el.getBoundingClientRect();
      if (b.width === 0 || b.height === 0) continue;
      if (b.left < r.left - 1 || b.top < r.top - 1 || b.right > r.right + 1 || b.bottom > r.bottom + 1) {
        const name = el.dataset && el.dataset.test ? "[data-test=" + el.dataset.test + "]" : el.tagName.toLowerCase();
        out.push("#" + id + " " + name + " (" + Math.round(b.left) + "," + Math.round(b.top)
                 + " to " + Math.round(b.right) + "," + Math.round(b.bottom) + "; card to "
                 + Math.round(r.right) + "," + Math.round(r.bottom) + ")");
        break;
      }
    }
  }
  return out;
})()"""


def check_kiosk(pg: UIPage, exp: dict, size, add_kiosk):
    """The kiosk view: everything fits the screen, the key content is visible, the fonts
    are large enough, and the details card stays out; and no card's content reaches
    outside its card."""
    w, h = size
    info = pg.js("__ui.page()")
    problems = []
    if info["sh"] > h + 1:
        problems.append(f"page is {info['sh']} px high at {w}x{h}: it must fit without scrolling")
    if info["sw"] > w + 1:
        problems.append(f"page is {info['sw']} px wide at {w}x{h}: {pg.js('__ui.overflowing()')}")
    hooks = (["rain-answer", "rain-probability", "now-temp", "now-station", "radar-step"]
             + (["chart-dry"] if exp["chart"] == "dry" else ["chart"]))
    for hook in hooks:
        els = pg.ui(hook)
        if not els or not all(e["visible"] for e in els):
            problems.append(f"[data-test={hook}] not visible in the kiosk view")
            continue
        for e in els:
            r = e["rect"]
            if r["x"] < -1 or r["y"] < -1 or r["right"] > w + 1 or r["bottom"] > h + 1:
                problems.append(f"[data-test={hook}] is outside the {w}x{h} screen ({round(r['x'])},{round(r['y'])} "
                                f"to {round(r['right'])},{round(r['bottom'])})")
                break
    for spill in pg.js(CONTAINED_JS):
        problems.append(f"{spill} reaches outside its card at {w}x{h}")
    if any(e["visible"] for e in pg.ui("details")):
        problems.append("[data-test=details] is visible: the kiosk view leaves out the technical details")
    add_kiosk(f"kiosk-{w}x{h}", problems)

