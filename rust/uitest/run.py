#!/usr/bin/env python3
"""UI contract: the web page in headless Chromium against the Rust app.

Per scenario (the contract suite's: recorded Berlin data, fake upstream,
frozen server clock) the Rust app is started; headless Chromium loads the
page in English (en-US) and German (de-DE), with the browser clock frozen
at the scenario's "now" (it runs on from there) and the browser in UTC, so
times must be shown in the location's time zone. The checks read what the
page shows through stable ``data-test`` hooks: content, not layout (see
``qwen/web/00_brief.md``, "UI contract"). Generic checks: no console errors
or CSP violations, same-origin requests only, contrast (WCAG AA, measured
on the rendered pixels) in both themes, no horizontal overflow at 360 px
(and nothing sticking out of the Details card), the tile columns per width,
the kiosk view without scrolling and its cards filled, control sizes, reduced
motion, the size budget, and that bad data or a failed /api/config doesn't
stop the page (faked responses, see ``cdp.Page.fake``). The ``sky``
scenario fakes the weather icon and the radar per scene (``SCENE_CASES``). The JS unit
tests (``unit/*.test.mjs``, ``node --test``) are checks too.

    # in the sandbox, after `cargo build`:
    python3 rust/uitest/run.py --binary /target/debug/wetter
    # only some checks must pass (the others are reported only):
    python3 rust/uitest/run.py --binary /target/debug/wetter --require 'unit/*' '*/console'
    # faster while working on one part:
    python3 rust/uitest/run.py --binary /target/debug/wetter --scenario rain --lang de
    # list the checks / save screenshots for a review:
    python3 rust/uitest/run.py --list
    python3 rust/uitest/run.py --binary /target/debug/wetter --shots /tmp/shots

Check names are ``scenario/lang/check`` (``rain/de/now-wind``), plus
``budget``, ``static-files`` and ``unit/<file>``. Stdlib only; needs
``chromium`` and ``node`` (both in the sandbox image).
"""
from __future__ import annotations

import argparse
import json
import math
import calendar
import fnmatch
import importlib.util
import pathlib
import re
import subprocess
import sys
import tempfile
import time
import types

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
STATIC = REPO / "app" / "static"
sys.path.insert(0, str(REPO / "rust" / "contract"))
sys.path.append(str(HERE))
# the contract suite's run.py, loaded by path (this file is a run.py too)
_spec = importlib.util.spec_from_file_location("contract_run", REPO / "rust" / "contract" / "run.py")
contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(contract)

from cdp import Browser  # noqa: E402
from expect import (  # noqa: E402
    ACCURACY_HEAD, ANSWER, ATTRIBUTION_LINKS, BUDGET_BYTES, CONFIG_RETRY_S, CONTRAST_GAP_S, CONTRAST_MOMENTS,
    CONTRAST_PCT, CONTRAST_VIEWS, FIXED, KIOSK_CHART_LABEL_PX, KIOSK_CHART_MIN,
    KIOSK_CHART_MIN_W, KIOSK_DRY_CHART_MAX, LAYOUT_COLUMNS, LAYOUT_MIN_TRACK, LAYOUT_SPACE, LAYOUT_WIDE,
    MAP_BEARING_TOLERANCE, MAP_MARKS, MAP_RADIUS_KM, MOTION_GAP_S, MOTION_MIN, NOW_STATION, GLASS_MIN_RATIO,
    GLASS_DELTA, GLASS_GAP_S, GLASS_SCENES, GLASS_VIEW, REASON_CASES, REASON_STATION, REASON_TEXT, SCENE_LABEL, VIEW_DESKTOP, VIEW_PHONE,
    OBS_STATIONS, KIOSK_FILL, KIOSK_FONT_SHARE, KIOSK_MIN_FONT, KIOSK_RADAR_SHARE,
    KIOSK_SIZES, LOCALES, MODEL_LABELS, NOW, RADAR_CAPTION, SCENARIO, SCENE_CASES, SCENE_SOURCE, SCENES,
    SOURCE_KIND, SOURCES, TZ, WEIGHTS, WHEN, WIZARD_DETAIL, WIZARD_LABEL)
from fakeup import FakeUpstream  # noqa: E402
from scenarios import SCENARIOS  # noqa: E402

PROBE = (HERE / "probe.js").read_text()
ALLOWED_EXT = {".html", ".js", ".css"}

# --- the list of checks (also what --list prints) ---------------------------

COMMON = ["console", "requests", "lang", "location", "location-detail", "theme-light", "theme-dark", "theme-icon",
          "contrast-light", "contrast-dark", "overflow-360", "buttons", "attribution"]
GLANCE = ["rain-answer", "rain-when", "rain-probability"]
RADAR = ["radar-steps", "radar-labels", "radar-caption", "radar-dry", "radar-max"]
NOW_CHECKS = list(NOW)
CHART = ["chart-svg", "chart-series", "chart-legend", "chart-y-labels", "chart-x-labels", "chart-unit", "chart-dry"]
DETAILS = ["details-closed", "details-weights", "details-signals", "details-weighting", "countdown-radar", "countdown-models",
           "countdown-page", "source-rows", "source-errors", "accuracy-table", "details-fit", "details-compact"]
KIOSK = [f"kiosk-{w}x{h}" for w, h in KIOSK_SIZES]
KIOSK_CHART = [f"kiosk-chart-{w}x{h}" for w, h in KIOSK_SIZES]
KIOSK_FILL_CHECKS = [f"kiosk-fill-{w}x{h}" for w, h in KIOSK_SIZES]
REFRESH = ["refresh-render-error", "refresh-config-retry"]
STATIONS = ["now-station", "now-fallback", "observation-stations", "station-map"]
LAYOUT = [f"layout-{w}" for w in LAYOUT_COLUMNS]
SKY = (["sky-layer"] + [f"scene-{c}" for c in SCENE_CASES] + [f"motion-{s}" for s in SCENES if s != "none"]
       + [f"still-{s}" for s in SCENES] + [f"contrast-{s}-{t}" for s in SCENES for t in ("light", "dark")]
       + [f"glass-{s}" for s in GLASS_SCENES])
REASON = [f"reason-{c}" for c in REASON_CASES]
VIEW = ["view-default", "view-toggle", "view-query", "view-phone"]


def check_names(scenario: str, lang: str) -> list[str]:
    if scenario in ("live", "rain"):
        names = COMMON + GLANCE + RADAR + NOW_CHECKS + CHART + DETAILS + KIOSK + KIOSK_FILL_CHECKS + STATIONS
        if scenario == "live":
            names = [n for n in names if not n.startswith("chart-") or n == "chart-dry"]
            names += REASON + (["theme-toggle"] + VIEW if lang == "en" else [])
        else:
            names += KIOSK_CHART + (["reduced-motion"] + REFRESH if lang == "en" else [])
        return names
    if scenario == "errors":
        return (COMMON + ["rain-answer", "rain-when", "rain-probability", "radar-unavailable", "now-unavailable",
                          "chart-unavailable", "now-station", "station-map"] + [n for n in DETAILS if n not in ("details-weights", "details-signals")])
    if scenario == "accuracy":
        return ["console", "requests", "location", "location-detail", "rain-probability", "details-closed",
                "details-weighting", "accuracy-table", "accuracy-head", "accuracy-note", "details-fit", "details-compact", "overflow-360"]
    if scenario == "fallback":
        return ["console", "now-station", "now-fallback"]
    if scenario == "sky":
        return ["console", "requests"] + LAYOUT + SKY
    if scenario == "unconfigured":
        return ["console", "requests", "lang", "setup-visible", "theme-light", "theme-dark", "theme-icon",
                "contrast-light", "contrast-dark", "overflow-360", "buttons"]
    if scenario == "wizard":
        return ["console", "validation"] if lang == "de" else ["console", "requests", "validation", "search",
                                                               "save", "location-long", "change"]
    raise ValueError(scenario)


UI_SCENARIOS = ["live", "rain", "errors", "accuracy", "unconfigured", "wizard", "fallback", "sky"]
SCENARIO_LANGS = {"wizard": ["de", "en"], "sky": ["en"]}  # the German validation runs before the English save
BACKEND = {"sky": "live"}  # UI scenarios that run on another scenario's app (with faked API answers)


def all_names(scenarios, langs) -> list[str]:
    names = ["budget", "static-files"] + [f"unit/{p.name}" for p in unit_files()]
    for sc in scenarios:
        for lang in SCENARIO_LANGS.get(sc, ["en", "de"]):
            if lang in langs:
                names += [f"{sc}/{lang}/{c}" for c in check_names(sc, lang)]
    return names


def unit_files() -> list[pathlib.Path]:
    return sorted((HERE / "unit").glob("*.test.mjs")) + sorted((HERE / "unit" / "more").glob("*.test.mjs"))


# --- small helpers ------------------------------------------------------------

def norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[   ]", " ", s or "")).strip()


def has(text: str, token: str) -> bool:
    """token in text, not as part of a longer number or word ("75%" is not in "175%").
    Spaces are optional between a number and its unit ("21 °" matches "21°")."""
    pattern = ""
    for i, ch in enumerate(norm(token)):
        if ch == " ":
            pattern += r"\s*"
            continue
        if i and token[i - 1].isdigit() and not ch.isdigit() and ch not in ".,:":
            pattern += r"\s*"
        pattern += re.escape(ch)
    return re.search(r"(?<![\w.,])" + pattern + r"(?!\w)", norm(text)) is not None


def one(items: list[dict], hook: str) -> tuple[dict | None, list[str]]:
    if not items:
        return None, [f"no element [data-test={hook}]"]
    if len(items) > 1:
        return None, [f"{len(items)} elements [data-test={hook}], expected one"]
    return items[0], []


def visible_one(page, hook) -> tuple[dict | None, list[str]]:
    el, problems = one(page.ui(hook), hook)
    if el and not el["visible"]:
        return None, [f"[data-test={hook}] is not visible"]
    return el, problems


def expect_text(page, hook, want: str) -> list[str]:
    el, problems = visible_one(page, hook)
    if el and norm(el["text"]) != norm(want):
        problems.append(f"[data-test={hook}] shows {el['text']!r}, expected {norm(want)!r}")
    return problems


def expect_tokens(page, hook, tokens: list[str]) -> list[str]:
    el, problems = visible_one(page, hook)
    if el:
        missing = [t for t in tokens if not has(el["text"], t)]
        if missing:
            problems.append(f"[data-test={hook}] shows {el['text']!r}, missing {missing}")
    return problems


def expect_hidden(page, hook) -> list[str]:
    shown = [e for e in page.ui(hook) if e["visible"]]
    return [f"[data-test={hook}] is visible ({shown[0]['text'][:60]!r}), expected hidden or absent"] if shown else []


def fmt_mm(v: float, lang: str, digits: int = 1) -> str:
    s = f"{v:.{digits}f}"
    return (s.replace(".", ",") if lang == "de" else s) + " mm"


# --- the page -------------------------------------------------------------

CLOCK = """(() => {
  const FAKE = Date.parse(%r), START = performance.now(), Real = Date;
  const now = () => FAKE + (performance.now() - START);
  function FakeDate(...a) {
    if (!new.target) return new Real(now()).toString();
    return a.length ? new Real(...a) : new Real(now());
  }
  FakeDate.prototype = Real.prototype;
  FakeDate.now = () => Math.floor(now());
  FakeDate.parse = Real.parse;
  FakeDate.UTC = Real.UTC;
  globalThis.Date = FakeDate;
  addEventListener("securitypolicyviolation", (e) =>
    console.error(`CSP violation: ${e.violatedDirective} ${e.blockedURI}`));
})();"""


class UIPage:
    def __init__(self, browser, base, sc_now, lang, width=1280, height=900, scheme="light",
                 reduced=False, query="?detailed", fakes=None):
        """query: "?detailed" (the content checks), "" (the default view) or "?kiosk"."""
        self.lang, self.locale, self.base = lang, LOCALES[lang], base
        self.p = browser.new_page()
        mobile = width < 600
        self.p.send("Emulation.setLocaleOverride", {"locale": self.locale})
        self.p.send("Emulation.setTimezoneOverride", {"timezoneId": "UTC"})
        self.p.send("Emulation.setDeviceMetricsOverride",
                    {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": mobile})
        if mobile:
            self.p.send("Emulation.setTouchEmulationEnabled", {"enabled": True})
        self.p.send("Emulation.setEmulatedMedia", {"features": [
            {"name": "prefers-color-scheme", "value": scheme},
            {"name": "prefers-reduced-motion", "value": "reduce" if reduced else "no-preference"}]})
        self.p.send("Page.addScriptToEvaluateOnNewDocument", {"source": CLOCK % sc_now})
        if fakes:
            self.p.fake(fakes)
        self.p.goto(base + "/" + query)
        self.settle()

    def settle(self):
        self.p.eval(PROBE)
        self.p.eval("new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")

    def reload(self):
        self.p._loaded = False
        self.p.send("Page.reload")
        self.p.wait_idle()
        self.settle()

    def ui(self, hook) -> list[dict]:
        return self.p.eval(f"__ui.info({hook!r})")

    def js(self, expr):
        return self.p.eval(expr)

    def times(self, isos: list[str]) -> list[str]:
        """The browser's own formatting of UTC times in the location's zone."""
        return [norm(t) for t in self.p.eval(
            f"{isos!r}.map((s) => new Intl.DateTimeFormat({self.locale!r}, "
            f"{{hour: 'numeric', minute: '2-digit', timeZone: {TZ!r}}}).format(new Date(s)))")]

    def click(self, hook=None, selector=None) -> list[str]:
        """A real mouse click in the middle of the element (it must not be covered)."""
        sel = selector or f'[data-test="{hook}"]'
        r = self.p.eval(f"""(() => {{
            const el = document.querySelector({sel!r});
            if (!el) return {{error: "no element " + {sel!r}}};
            el.scrollIntoView({{block: "center", inline: "center"}});
            const b = el.getBoundingClientRect();
            const x = b.x + b.width / 2, y = b.y + b.height / 2;
            const top = document.elementFromPoint(x, y);
            if (!top || !(el === top || el.contains(top)))
                return {{error: {sel!r} + " is covered by " + (top ? top.tagName.toLowerCase() : "nothing")}};
            return {{x, y}};
        }})()""")
        if "error" in r:
            return [r["error"]]
        for kind in ("mousePressed", "mouseReleased"):
            self.p.send("Input.dispatchMouseEvent", {"type": kind, "x": r["x"], "y": r["y"],
                                                     "button": "left", "clickCount": 1})
        self.p.wait_idle(idle=0.3)
        self.settle()
        return []

    def type_into(self, hook, text) -> list[str]:
        ok = self.p.eval(f"""(() => {{
            const el = document.querySelector('[data-test="{hook}"]');
            if (!el) return false;
            el.focus(); if (el.select) el.select(); return true;
        }})()""")
        if not ok:
            return [f"no element [data-test={hook}]"]
        self.p.send("Input.insertText", {"text": text})
        return []

    def shot_b64(self) -> str:
        """The viewport as a base64 PNG (what the user sees now)."""
        return self.p.send("Page.captureScreenshot", {"format": "png"}, timeout=60)["data"]

    def frame(self):
        self.p.eval("new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")

    def close(self):
        self.p.close()


# --- checks on one loaded page -------------------------------------------------

def check_common_a(pg: UIPage, sc: str, exp: dict, add):
    """Desktop, light theme: content checks."""
    lang = pg.lang
    info = pg.js("__ui.page()")
    add("lang", [] if info["lang"] == lang else [f'<html lang="{info["lang"]}">, expected "{lang}"'])
    if "location" in exp:
        add("location", expect_tokens(pg, "location", exp["location"]))
        add("location-detail", expect_tokens(pg, "location-detail", exp["location_detail"]))
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


def contrast_problems(pg) -> list[str]:
    """WCAG AA for every visible text against the pixels drawn behind it (the text
    made transparent for the screenshot), so translucent tiles over a moving sky
    count as they look: CONTRAST_MOMENTS moments, scrolled through the page; per
    text the worst moment counts, and within it the CONTRAST_PCT worst pixels may
    be below (a raindrop crossing a word)."""
    worst: dict[str, dict] = {}
    for m in range(CONTRAST_MOMENTS):
        if m:
            time.sleep(CONTRAST_GAP_S)
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
    for hook, tokens in NOW.items():
        add(hook, expect_tokens(pg, hook, tokens[pg.lang]))


def check_chart(pg: UIPage, exp: dict, add):
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


def check_details(pg: UIPage, sc: str, exp: dict, names: list[str], add):
    lang = pg.lang
    det, problems = one(pg.ui("details"), "details")
    if det:
        if det["tag"] != "details":
            problems.append(f"[data-test=details] is a <{det['tag']}>, expected <details>")
        elif det["open"]:
            problems.append("[data-test=details] is open on load, expected closed")
        inside = [h for h in ("details-weights", "source-row", "accuracy-row", "accuracy-status")
                  if any(e["visible"] for e in pg.ui(h))]
        if inside:
            problems.append(f"visible before opening the details: {inside}")
    add("details-closed", problems)
    if det and det["tag"] == "details" and not det["open"]:
        g = pg.js('__ui.summaryGaps("details")')
        if g and g["below"] > g["above"] + 6:
            add("details-compact", [f"closed [data-test=details]: {g['below']:.0f} px below the summary, "
                                    f"{g['above']:.0f} px above it (at most 6 px more below than above)"])
        else:
            add("details-compact", [])
    if not det or det["tag"] != "details":
        for check in DETAILS[1:]:
            add(check, ['not checked: needs a <details data-test="details"> to open'])
        return
    problems = pg.click(selector='[data-test="details"] > summary')
    if problems:
        add("details-closed", problems)
        return
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
    add("details-fit", pg.js('__ui.sticksOut("details")'))
    if "accuracy-table" in names:
        add("accuracy-table", accuracy_problems(pg, exp))
    if "accuracy-head" in names:
        add("accuracy-head", expect_tokens(pg, "accuracy-head", ACCURACY_HEAD[pg.lang]))
    if "accuracy-note" in names:  # the fixture has rain hours, so the no-rain note stays hidden
        add("accuracy-note", expect_text(pg, "accuracy-note", FIXED["accuracy.note"][pg.lang])
            + expect_hidden(pg, "accuracy-no-rain"))


def accuracy_problems(pg, exp) -> list[str]:
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


def check_kiosk(pg: UIPage, exp: dict, size, add_kiosk):
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
    for hook, px in KIOSK_MIN_FONT.items():
        els = [e for e in pg.ui(hook) if e["visible"]]
        if els and els[0]["fontSize"] < px:
            problems.append(f"[data-test={hook}] font size {els[0]['fontSize']:.0f} px, at least {px} px in the kiosk view")
    if any(e["visible"] for e in pg.ui("details")):
        problems.append("[data-test=details] is visible: the kiosk view leaves out the technical details")
    add_kiosk(f"kiosk-{w}x{h}", problems)


# --- one scenario ---------------------------------------------------------------

class Results:
    def __init__(self):
        self.problems: dict[str, list[str]] = {}

    def add(self, name, problems):
        self.problems.setdefault(name, []).extend(problems)


def start_app(sc: dict, args, tmp: pathlib.Path):
    fake = FakeUpstream(sc["routes"])
    db = tmp / "weather.db"
    if sc.get("seed"):
        contract.seed_db(db, sc["seed"], sc["now"])
    env = {"WEATHER_CONFIG": str(contract.make_config(tmp, fake.base)), "DATABASE_PATH": str(db),
           "WETTER_FAKE_NOW": sc["now"], **sc["env"]}
    port = contract.free_port()
    ns = types.SimpleNamespace(backend="rust", binary=args.binary, log=args.log)
    proc = contract.start_backend(ns, port, env)
    error = contract.wait_ready(port, proc)
    return fake, proc, port, error


def run_scenario(name: str, browsers: dict, args, res: Results):
    sc = next(s for s in SCENARIOS if s["name"] == BACKEND.get(name, name))
    langs = [lang for lang in SCENARIO_LANGS.get(name, ["en", "de"]) if lang in browsers]
    with tempfile.TemporaryDirectory(prefix="uitest-") as tmp:
        fake, proc, port, error = start_app(sc, args, pathlib.Path(tmp))
        try:
            if error:
                for lang in langs:
                    for c in check_names(name, lang):
                        res.add(f"{name}/{lang}/{c}", [f"app did not start: {error}"])
                return
            base = f"http://127.0.0.1:{port}"
            for lang in langs:
                prefix = f"{name}/{lang}/"
                names = check_names(name, lang)

                def add(check, problems, prefix=prefix, names=names):
                    if check in names:
                        res.add(prefix + check, problems)

                try:
                    run_pages(name, sc, browsers[lang], base, lang, names, add, args)
                except Exception as exc:  # noqa: BLE001 - report it, go on with the next language
                    add("console", [f"harness error: {exc!r}"])
                    for c in names:
                        if prefix + c not in res.problems:
                            add(c, [f"not checked: the page run stopped early ({exc!r})"])
        finally:
            contract.stop_backend(proc)
            fake.stop()


def run_pages(name, sc, browser, base, lang, names, add, args):
    exp = SCENARIO.get(name, {})
    errors, requests = [], []
    icons = {}  # theme -> the theme toggle's visible icons
    shots = args.shots

    def done(pg: UIPage):
        pg.p.pump()
        errors.extend(pg.p.errors)
        requests.extend(pg.p.requests)
        pg.close()

    def shot(pg, variant, full=True):
        if shots:
            pg.p.screenshot(str(pathlib.Path(shots) / f"{name}-{lang}-{variant}.png"), full_page=full)

    if name == "wizard":
        run_wizard(browser, base, sc, lang, add, done, shot)
    elif name == "fallback":
        pg = UIPage(browser, base, sc["now"], lang)
        add("now-station", expect_tokens(pg, "now-station", NOW_STATION[lang]))
        add("now-fallback", now_fallback_problems(pg))
        shot(pg, "desktop-light")
        done(pg)
    elif name == "sky":
        run_sky(browser, base, sc, lang, add, done, shot)
    elif name == "unconfigured":
        pg = UIPage(browser, base, sc["now"], lang)
        info = pg.js("__ui.page()")
        add("lang", [] if info["lang"] == lang else [f'<html lang="{info["lang"]}">, expected "{lang}"'])
        problems = [p for hook in ("setup", "setup-search", "setup-lat", "setup-lon", "setup-tz", "setup-save")
                    for p in visible_one(pg, hook)[1]]
        add("setup-visible", problems + expect_hidden(pg, "rain-answer"))
        add("theme-light", theme_problems(info, "light"))
        icons["light"] = pg.js('__ui.icons("theme-toggle")')
        add("contrast-light", contrast_problems(pg))
        add("buttons", pg.js("__ui.controls()"))
        shot(pg, "desktop-light")
        done(pg)
    else:
        # A: desktop, light; content checks, then the details opened
        pg = UIPage(browser, base, sc["now"], lang)
        if name == "accuracy":
            add("location", expect_tokens(pg, "location", exp["location"]))
            add("location-detail", expect_tokens(pg, "location-detail", exp["location_detail"]))
            add("rain-probability", expect_tokens(pg, "rain-probability", [exp["probability"][lang]]))
        else:
            check_common_a(pg, name, exp, add)
            icons["light"] = pg.js('__ui.icons("theme-toggle")')
            check_glance(pg, exp, add)
            if exp["radar"] is None:
                add("radar-unavailable", visible_one(pg, "radar-unavailable")[1]
                    + [f"{n} rendered [data-test=radar-step] without radar" for n in
                       [sum(e["rendered"] for e in pg.ui("radar-step"))] if n])
            else:
                check_radar(pg, exp, add)
            if exp["now"]:
                check_now(pg, add)
                add("now-station", expect_tokens(pg, "now-station", NOW_STATION[lang]))
                add("now-fallback", [f"{n} visible [data-test=now-fallback]: no value fell back here"
                                     for n in [sum(e["visible"] for e in pg.ui("now-fallback"))] if n])
            else:
                add("now-unavailable", expect_text(pg, "now-unavailable", FIXED["now.unavailable"][lang])
                    + expect_hidden(pg, "now-temp"))
                add("now-station", expect_hidden(pg, "now-station"))
            check_chart(pg, exp, add)
        shot(pg, "desktop-light")
        check_details(pg, name, exp, names, add)
        shot(pg, "desktop-details")
        done(pg)
        if name == "accuracy":
            pass
        else:
            # B: desktop, dark
            pg = UIPage(browser, base, sc["now"], lang, scheme="dark")
            add("theme-dark", theme_problems(pg.js("__ui.page()"), "dark"))
            icons["dark"] = pg.js('__ui.icons("theme-toggle")')
            add("contrast-dark", contrast_problems(pg))
            shot(pg, "desktop-dark")
            done(pg)
    if name in ("live", "rain", "errors", "unconfigured", "accuracy"):
        # C: phone, 360 px, everything opened
        pg = UIPage(browser, base, sc["now"], lang, width=360, height=740)
        pg.js("__ui.openDetails()")
        pg.settle()
        info = pg.js("__ui.page()")
        add("overflow-360", [] if info["sw"] <= 361 and info["iw"] <= 361 else
            [f"page is {info['sw']} px wide at 360 px (horizontal scrolling): {pg.js('__ui.overflowing()')}"])
        add("details-fit", [f"at 360 px: {p}" for p in pg.js('__ui.sticksOut("details")')])
        shot(pg, "phone-360")
        done(pg)
    if name == "unconfigured":
        pg = UIPage(browser, base, sc["now"], lang, scheme="dark")
        add("theme-dark", theme_problems(pg.js("__ui.page()"), "dark"))
        icons["dark"] = pg.js('__ui.icons("theme-toggle")')
        add("contrast-dark", contrast_problems(pg))
        done(pg)
    if "theme-icon" in names:
        add("theme-icon", theme_icon_problems(icons))
    if name in ("live", "rain"):
        for size in KIOSK_SIZES:
            pg = UIPage(browser, base, sc["now"], lang, width=size[0], height=size[1], query="?kiosk")
            check_kiosk(pg, exp, size, add)
            if f"kiosk-chart-{size[0]}x{size[1]}" in names:
                add(f"kiosk-chart-{size[0]}x{size[1]}", kiosk_chart_problems(pg, size))
            add(f"kiosk-fill-{size[0]}x{size[1]}", kiosk_fill_problems(pg, exp, size))
            shot(pg, f"kiosk-{size[0]}x{size[1]}", full=False)
            done(pg)
    if "theme-toggle" in names:
        add("theme-toggle", theme_toggle(browser, base, sc, lang, done))
    if any(n.startswith("reason-") for n in names):
        run_reasons(browser, base, sc, lang, add)
    if "view-default" in names:
        run_views(browser, base, sc, lang, add)
    for w in LAYOUT_COLUMNS:
        if f"layout-{w}" in names:
            pg = UIPage(browser, base, sc["now"], lang, width=w, height=740 if w < 600 else 900)
            add(f"layout-{w}", layout_problems(pg, w))
            shot(pg, f"layout-{w}")
            done(pg)
    if "refresh-render-error" in names:
        add("refresh-render-error", refresh_render_error(browser, base, sc, lang))
    if "refresh-config-retry" in names:
        add("refresh-config-retry", refresh_config_retry(browser, base, sc, lang))
    if "reduced-motion" in names:
        pg = UIPage(browser, base, sc["now"], lang, reduced=True)
        time.sleep(0.3)
        running = pg.js("__ui.animations()")
        add("reduced-motion", [f"animations still running with prefers-reduced-motion: {running}"] if running else [])
        done(pg)

    own = base + "/"
    foreign = sorted({u for u in requests if not (u.startswith(own) or u.startswith("data:"))})
    add("requests", [f"request outside the app: {u}" for u in foreign])
    add("console", list(dict.fromkeys(errors))[:8])


def layout_problems(pg: UIPage, w: int) -> list[str]:
    """The tiles flow with the width: LAYOUT_COLUMNS grid columns, the glance first
    (top left) and at least as wide as any other tile, Details across the full
    width, no tile overlapping another, no horizontal scrolling; wide screens use
    their width instead of one narrow column."""
    t = pg.js("__ui.tiles()")
    if not t:
        return ["no main#dashboard"]
    want = LAYOUT_COLUMNS[w]
    problems = []
    if t["columns"] != want:
        how = f"grid-template-columns {[round(x) for x in t['tracks']]}" if t["grid"] else "not a CSS grid"
        problems.append(f"{t['columns']} tile column(s) at {w} px ({how}), expected {want}")
    tiles = t["list"]
    by_id = {x["id"]: x for x in tiles}
    if not tiles or tiles[0]["id"] != "glance":
        problems.append(f"the first tile is {tiles[0]['id'] if tiles else None!r}, expected #glance")
    g = by_id.get("glance")
    if g:
        if any(o["y"] < g["y"] - 1 for o in tiles if o is not g):
            problems.append("a tile starts above #glance: the glance comes first")
        if g["x"] > t["x"] + 1:
            problems.append(f"#glance starts at x={g['x']:.0f}, not at the left edge of the tiles ({t['x']:.0f})")
        wider = [o["id"] for o in tiles if o["id"] not in ("glance", "details") and o["w"] > g["w"] + 1]
        if wider:
            problems.append(f"{wider} wider than #glance ({g['w']:.0f} px): the glance is the widest tile")
    d = by_id.get("details")
    if not d:
        problems.append("no visible #details tile")
    elif d["w"] < t["w"] - 2:
        problems.append(f"#details is {d['w']:.0f} px wide, the tiles {t['w']:.0f} px: Details spans the full width")
    for i, a in enumerate(tiles):
        for b in tiles[i + 1:]:
            ox = min(a["right"], b["right"]) - max(a["x"], b["x"])
            oy = min(a["bottom"], b["bottom"]) - max(a["y"], b["y"])
            if ox > 1 and oy > 1:
                problems.append(f"#{a['id']} and #{b['id']} overlap ({ox:.0f}x{oy:.0f} px)")
    info = pg.js("__ui.page()")
    if info["sw"] > w + 1:
        problems.append(f"page is {info['sw']} px wide at {w} px: {pg.js('__ui.overflowing()')}")
    if w >= LAYOUT_WIDE:
        if t["w"] < LAYOUT_SPACE * w:
            problems.append(f"the tiles use {t['w']:.0f} px of {w} px, at least {LAYOUT_SPACE * w:.0f} px "
                            f"({LAYOUT_SPACE:.0%}): wide screens get more columns, not wide margins")
        narrow = [round(x) for x in t["tracks"] if x < LAYOUT_MIN_TRACK]
        if narrow:
            problems.append(f"columns {narrow} px narrower than {LAYOUT_MIN_TRACK} px")
    return problems


# --- the sky (A3): faked /api/now icon and radar per scene ---------------------------------

def _get_json(url: str):
    import urllib.request
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read())


def scene_fakes(case: str, now_body: dict, radar_body: dict, station: bool = True) -> dict:
    """/api/now and /api/radar/next-hour for a SCENE_CASES entry (the app's own
    answers with the icon and the radar steps replaced)."""
    icon, radar, _ = SCENE_CASES[case]
    if icon == "no-observation":
        now = {"available": False, "age_seconds": None, "stale": False, "conditions": None}
    else:
        now = json.loads(json.dumps(now_body))
        now["conditions"]["icon"] = icon
        if not station:
            now["conditions"]["station"] = None
    rb = json.loads(json.dumps(radar_body))
    if radar == "unavailable":
        rb["available"], rb["steps"] = False, []
    else:
        for st in rb["steps"]:
            st["precip_mm"] = 0.0
        for i, mm in (radar or {}).items():
            rb["steps"][i]["precip_mm"] = mm
    # enough answers for every request of one page (later ones would reach the app)
    return {"/api/now": [(200, json.dumps(now))] * 8, "/api/radar/next-hour": [(200, json.dumps(rb))] * 8}


def scene_of(pg: UIPage) -> str | None:
    return pg.js("document.documentElement.getAttribute('data-scene')")


def sky_layer_problems(pg: UIPage) -> list[str]:
    """One [data-test=sky] layer: fixed, covering the viewport, behind the tiles,
    hidden from screen readers."""
    s = pg.js("__ui.sky()")
    if s["count"] != 1:
        return [f"{s['count']} elements [data-test=sky], expected one (the animated sky behind the tiles)"]
    problems = []
    if s["position"] != "fixed":
        problems.append(f"[data-test=sky] has position {s['position']}, expected fixed (it stays while the page scrolls)")
    r = s["rect"]
    if r["x"] > 0.5 or r["y"] > 0.5 or r["x"] + r["w"] < s["vw"] - 0.5 or r["y"] + r["h"] < s["vh"] - 0.5:
        problems.append(f"[data-test=sky] covers ({r['x']:.0f},{r['y']:.0f}) {r['w']:.0f}x{r['h']:.0f}, "
                        f"expected the whole {s['vw']}x{s['vh']} viewport")
    if s["ariaHidden"] != "true":
        problems.append('[data-test=sky] needs aria-hidden="true" (decoration)')
    if s["covered"]:
        problems.append(f"[data-test=sky] is on top of the tiles {s['covered']}: it belongs behind them")
    return problems


def motion_problems(pg: UIPage, scene: str, moving: bool) -> list[str]:
    """Two screenshots of the sky alone (everything else hidden), MOTION_GAP_S apart:
    they differ (it moves) or, under reduced motion, are equal (a still picture)."""
    got = scene_of(pg)
    if got != scene:
        return [f"data-scene={got!r}, expected {scene!r} (needed to judge this scene's sky)"]
    if not pg.js("__ui.onlySky(true)"):
        return ["no [data-test=sky]"]
    if not moving:
        time.sleep(0.3)  # an entrance transition may finish first
    pg.frame()
    a = pg.shot_b64()
    time.sleep(MOTION_GAP_S)
    b = pg.shot_b64()
    share = pg.js(f"__ui.diff({json.dumps(a)}, {json.dumps(b)})")
    pg.js("__ui.onlySky(false)")
    if moving and share < MOTION_MIN:
        return [f"the sky changed {share:.4%} of its pixels in {MOTION_GAP_S} s, at least {MOTION_MIN:.1%}: "
                "it should move"]
    if not moving and share > 0:
        return [f"with prefers-reduced-motion the sky changed {share:.4%} of its pixels in {MOTION_GAP_S} s: "
                f"expected a still picture (running: {pg.js('__ui.animations()')})"]
    return []


def run_sky(browser, base, sc, lang, add, done, shot):
    now_body = _get_json(base + "/api/now")
    radar_body = _get_json(base + "/api/radar/next-hour")
    for case, (icon, radar, want) in SCENE_CASES.items():
        pg = UIPage(browser, base, sc["now"], lang, fakes=scene_fakes(case, now_body, radar_body))
        got = scene_of(pg)
        add(f"scene-{case}", [] if got == want else
            [f"<html data-scene={got!r}> with icon {icon!r} and radar {radar!r}, expected {want!r}"])
        if case == "cloudy":
            add("sky-layer", sky_layer_problems(pg))
        done(pg)
    for scene in SCENES:
        fakes = scene_fakes(SCENE_SOURCE[scene], now_body, radar_body)
        if scene != "none":
            pg = UIPage(browser, base, sc["now"], lang, fakes=fakes)
            add(f"motion-{scene}", motion_problems(pg, scene, moving=True))
            done(pg)
        pg = UIPage(browser, base, sc["now"], lang, reduced=True, fakes=fakes)
        add(f"still-{scene}", motion_problems(pg, scene, moving=False))
        done(pg)
        if scene in GLASS_SCENES:
            add(f"glass-{scene}", [p for theme in ("light", "dark")
                                   for p in glass_problems(browser, base, sc, lang, scene, theme, fakes)])
        for theme in ("light", "dark"):
            problems = []
            for w, h, query in CONTRAST_VIEWS:
                view = f"{w}x{h}{' kiosk' if query else ''}"
                pg = UIPage(browser, base, sc["now"], lang, width=w, height=h, scheme=theme, query=query, fakes=fakes)
                got = scene_of(pg)
                if got != scene:
                    problems.append(f"{view}: data-scene={got!r}, expected {scene!r}")
                problems += [f"{view}: {p}" for p in contrast_problems(pg)]
                if w >= 1280:  # frames for the review
                    for i in range(3):
                        shot(pg, f"scene-{scene}-{theme}-{view.replace(' ', '-')}-{i}", full=False)
                        time.sleep(0.4)
                done(pg)
            add(f"contrast-{scene}-{theme}", problems)


def glass_problems(browser, base, sc, lang, scene, theme, fakes) -> list[str]:
    """The default view at GLASS_VIEW, text made transparent: the moving sky changes
    the pixels inside the tiles at least GLASS_MIN_RATIO as much as outside them."""
    w, h = GLASS_VIEW
    pg = UIPage(browser, base, sc["now"], lang, width=w, height=h, scheme=theme, query="", fakes=fakes)
    try:
        got = scene_of(pg)
        if got != scene:
            return [f"{theme}: data-scene={got!r}, expected {scene!r}"]
        t = pg.js("__ui.tiles()")
        rects = [{k: x[k] for k in ("x", "y", "w", "h")} for x in (t["list"] if t else []) if x["h"] > 0]
        if not rects:
            return [f"{theme}: no visible tiles in main#dashboard"]
        pg.js("__ui.hideText(true)")
        pg.frame()
        a = pg.shot_b64()
        time.sleep(GLASS_GAP_S)
        b = pg.shot_b64()
        r = pg.js(f"__ui.diffIn({json.dumps(a)}, {json.dumps(b)}, {json.dumps(rects)}, {GLASS_DELTA})")
        pg.js("__ui.hideText(false)")
        if not r or r["outside"] == 0:
            return [f"{theme}: the sky doesn't change visibly outside the tiles within {GLASS_GAP_S} s"]
        if r["inside"] < GLASS_MIN_RATIO * r["outside"]:
            return [f"{theme} {w}x{h}: inside the tiles {r['inside']:.2%} of the pixels change visibly in {GLASS_GAP_S} s, "
                    f"outside {r['outside']:.2%}: at least {GLASS_MIN_RATIO:.0%} of that must show through the "
                    f"tiles ({', '.join('#' + x['id'] for x in t['list'])})"]
        return []
    finally:
        pg.close()


def reason_text(case: str, lang: str) -> str | None:
    src, form, _ = REASON_CASES[case]
    if form is None:
        return None
    icon, _, scene = SCENE_CASES[src]
    i = 0 if lang == "en" else 1
    name, km = REASON_STATION
    return REASON_TEXT[form][lang].format(scene=SCENE_LABEL[scene][i], name=name, km=km[lang],
                                          station=SCENE_LABEL[icon][i] if icon in SCENE_LABEL else "")


def run_reasons(browser, base, sc, lang, add):
    """[data-test=sky-reason]: what the sky shows and which source decided it (REASON_CASES)."""
    now_body = _get_json(base + "/api/now")
    radar_body = _get_json(base + "/api/radar/next-hour")
    for case, (src, form, listed) in REASON_CASES.items():
        pg = UIPage(browser, base, sc["now"], lang, fakes=scene_fakes(src, now_body, radar_body, station=listed))
        want = reason_text(case, lang)
        problems = expect_hidden(pg, "sky-reason") if want is None else expect_text(pg, "sky-reason", want)
        got = scene_of(pg)
        if got != SCENE_CASES[src][2]:
            problems.append(f"data-scene={got!r}, expected {SCENE_CASES[src][2]!r}")
        add(f"reason-{case}", problems)
        pg.close()


def view_of(pg: UIPage) -> str | None:
    return pg.js("document.documentElement.getAttribute('data-view')")


def run_views(browser, base, sc, lang, add):
    """The big view (the former kiosk look) by default; [data-test=view-toggle] switches to
    the detailed view and back, remembered per device; ?detailed and ?kiosk force a view
    (?kiosk is the locked wall display: no view or location button)."""
    w, h = VIEW_DESKTOP
    pg = UIPage(browser, base, sc["now"], lang, width=w, height=h, query="")
    problems = [] if view_of(pg) == "big" else [f'<html data-view={view_of(pg)!r}>, expected "big" by default']
    problems += [f"default view: {p}" for hook in ("view-toggle", "location-button", "rain-answer", "now-temp")
                 for p in visible_one(pg, hook)[1]]
    if any(e["visible"] for e in pg.ui("details")):
        problems.append("default view: [data-test=details] is visible; the big view leaves the details out")
    info = pg.js("__ui.page()")
    if info["sh"] > h + 1 or info["sw"] > w + 1:
        problems.append(f"default view at {w}x{h}: the page is {info['sw']}x{info['sh']} px, it must fit one screen")
    add("view-default", problems)
    problems = []
    for step, want in (("first click", "detailed"), ("after reload", "detailed"), ("second click", "big"),
                       ("after reload", "big")):
        if step.startswith("after"):
            pg.reload()
        else:
            problems += pg.click("view-toggle")
        got = view_of(pg)
        if got != want:
            problems.append(f"{step}: data-view={got!r}, expected {want!r}")
        details = any(e["visible"] for e in pg.ui("details"))
        if details != (want == "detailed"):
            problems.append(f"{step}: [data-test=details] {'visible' if details else 'hidden'} in the {want} view")
    add("view-toggle", problems)
    pg.close()
    pg = UIPage(browser, base, sc["now"], lang, width=w, height=h)
    problems = [] if view_of(pg) == "detailed" else [f"?detailed: data-view={view_of(pg)!r}, expected 'detailed'"]
    pg.close()
    pg = UIPage(browser, base, sc["now"], lang, width=w, height=h, query="")
    problems += pg.click("view-toggle")  # stores the detailed view; ?kiosk must still be big
    pg.p.goto(base + "/?kiosk")
    pg.settle()
    if view_of(pg) != "big":
        problems.append(f"?kiosk after choosing the detailed view: data-view={view_of(pg)!r}, expected 'big'")
    for hook in ("view-toggle", "location-button"):
        problems += [f"?kiosk: {p}" for p in expect_hidden(pg, hook)]
    add("view-query", problems)
    pg.close()
    w, h = VIEW_PHONE
    pg = UIPage(browser, base, sc["now"], lang, width=w, height=h, query="")
    problems = [] if view_of(pg) == "big" else [f"phone: data-view={view_of(pg)!r}, expected 'big'"]
    problems += [f"phone: {p}" for hook in ("view-toggle", "rain-answer", "rain-probability", "now-temp")
                 for p in visible_one(pg, hook)[1]]
    info = pg.js("__ui.page()")
    if info["sw"] > w + 1:
        problems.append(f"phone: the page is {info['sw']} px wide at {w} px: {pg.js('__ui.overflowing()')}")
    add("view-phone", problems)
    pg.close()


def now_fallback_problems(pg: UIPage) -> list[str]:
    """fallback scenario: cloud cover came from Potsdam (one mark at that value); the dew
    point's fallback source isn't listed, so no mark for it."""
    marks = [e for e in pg.ui("now-fallback") if e["visible"]]
    if len(marks) != 1:
        return [f"{len(marks)} visible [data-test=now-fallback], expected 1 (cloud cover from Potsdam)"]
    m, problems = marks[0], []
    if m["attrs"].get("data-field") != "cloud_cover_pct":
        problems.append(f'[data-test=now-fallback] data-field={m["attrs"].get("data-field")!r}, expected "cloud_cover_pct"')
    if not has(m["text"] + " " + m["attrs"].get("aria-label", "") + " " + m["attrs"].get("title", ""), "Potsdam"):
        problems.append(f"[data-test=now-fallback] {m['text']!r} doesn't name Potsdam")
    return problems


def observation_station_problems(pg: UIPage) -> list[str]:
    rows = [e for e in pg.ui("observation-station") if e["visible"]]
    if len(rows) != len(OBS_STATIONS):
        return [f"{len(rows)} visible [data-test=observation-station], expected {len(OBS_STATIONS)} (nearest first)"]
    problems = []
    for e, (name, km_en, km_de, hours) in zip(rows, OBS_STATIONS):
        for want in (name, km_en if pg.lang == "en" else km_de, hours):
            if not has(e["text"], want):
                problems.append(f"observation station row {e['text']!r} lacks {want!r} (rows nearest first)")
    return problems


def station_map_problems(pg: UIPage, exp: dict) -> list[str]:
    """The schematic map: the location in the middle, one mark per DWD station at its bearing
    and in distance order, the radar radius as a circle to the same scale, north and a scale."""
    marks = [e for e in pg.ui("map-station") if e["visible"]]
    if not exp.get("now"):
        return [f"{len(marks)} visible [data-test=map-station] without any station data"] if marks else []
    svg, problems = visible_one(pg, "station-map")
    if not svg:
        return problems
    if svg["tag"] != "svg" or svg["attrs"].get("role") != "img" or not svg["attrs"].get("aria-label"):
        problems.append('[data-test=station-map] must be an <svg role="img" aria-label="…">')
    loc, p = visible_one(pg, "map-location")
    problems += p
    for hook in ("map-radius", "map-north", "map-scale"):
        problems += visible_one(pg, hook)[1]
    scale = [e for e in pg.ui("map-scale") if e["visible"]]
    if scale and "km" not in scale[0]["text"]:
        problems.append(f"[data-test=map-scale] {scale[0]['text']!r} has no km")
    got = {e["attrs"].get("data-station"): e for e in marks}
    if sorted(got) != sorted(MAP_MARKS):
        return problems + [f"[data-test=map-station] data-station {sorted(got)}, expected {sorted(MAP_MARKS)} "
                           "(one mark per DWD station id)"]
    if not loc:
        return problems

    def centre(e):
        r = e["rect"]
        return r["x"] + r["w"] / 2, r["y"] + r["h"] / 2

    lx, ly = centre(loc)
    px = {}
    for sid, (bearing, km) in MAP_MARKS.items():
        x, y = centre(got[sid])
        dx, dy = x - lx, y - ly
        px[sid] = math.hypot(dx, dy)
        angle = math.degrees(math.atan2(dx, -dy)) % 360
        off = min(abs(angle - bearing), 360 - abs(angle - bearing))
        if off > MAP_BEARING_TOLERANCE:
            problems.append(f"map mark {sid} at {angle:.0f}° from the location, expected {bearing}° "
                            f"(±{MAP_BEARING_TOLERANCE}°; north is up)")
    near, far = sorted(MAP_MARKS, key=lambda k: MAP_MARKS[k][1])
    if px[near] >= px[far]:
        problems.append(f"map mark {near} ({MAP_MARKS[near][1]} km) is not nearer the centre than {far} "
                        f"({MAP_MARKS[far][1]} km)")
    radius = [e for e in pg.ui("map-radius") if e["visible"]]
    if radius and px[far] > 0:
        r_px = max(radius[0]["rect"]["w"], radius[0]["rect"]["h"]) / 2
        want = px[far] * MAP_RADIUS_KM / MAP_MARKS[far][1]
        if not 0.7 * want <= r_px <= 1.3 * want:
            problems.append(f"[data-test=map-radius] radius {r_px:.1f} px, expected about {want:.1f} px "
                            f"({MAP_RADIUS_KM} km at the stations' scale)")
    return problems


def kiosk_chart_problems(pg: UIPage, size) -> list[str]:
    """The chart fills its share of the kiosk screen instead of a short strip."""
    w, h = size
    els = [e for e in pg.ui("chart") if e["visible"]]
    if not els:
        return ["[data-test=chart] not visible in the kiosk view"]
    r, problems = els[0]["rect"], []
    if r["h"] < KIOSK_CHART_MIN * h:
        problems.append(f"[data-test=chart] is {r['h']:.0f} px high at {w}x{h}, "
                        f"at least {KIOSK_CHART_MIN * h:.0f} px ({KIOSK_CHART_MIN:.0%} of the screen height)")
    if r["w"] < KIOSK_CHART_MIN_W * w:
        problems.append(f"[data-test=chart] is {r['w']:.0f} px wide at {w}x{h}, "
                        f"at least {KIOSK_CHART_MIN_W * w:.0f} px ({KIOSK_CHART_MIN_W:.0%} of the screen width)")
    # what is drawn (labels, lines) must use the box: taller must not mean letterboxed
    drawn = [e["rect"] for hook in ("chart-y-label", "chart-x-label", "chart-series") for e in pg.ui(hook) if e["rendered"]]
    if drawn:
        span = max(d["right"] for d in drawn) - min(d["x"] for d in drawn)
        if span < 0.85 * r["w"]:
            problems.append(f"the chart draws {span:.0f} px wide inside its {r['w']:.0f} px box "
                            "(letterboxed: the plot must use the box's width)")
    labels = [e for e in pg.ui("chart-x-label") if e["visible"]]
    if labels and labels[0]["rect"]["h"] < KIOSK_CHART_LABEL_PX:
        problems.append(f"[data-test=chart-x-label] is drawn {labels[0]['rect']['h']:.1f} px high in the kiosk "
                        f"view, at least {KIOSK_CHART_LABEL_PX} px (a scaled-down SVG shrinks its text)")
    return problems


# Per kiosk card: its inner box (padding off) and the span of what it shows, measured on
# what is drawn (text line boxes, empty boxes like the radar steps, SVGs), so a stretched
# wrapper doesn't count as content.
KIOSK_CARDS_JS = """(() => {
  const out = {};
  for (const id of ["glance", "now", "chart-card"]) {
    const c = document.getElementById(id);
    if (!c || !c.checkVisibility()) continue;
    const r = c.getBoundingClientRect(), cs = getComputedStyle(c);
    const top = r.top + parseFloat(cs.borderTopWidth) + parseFloat(cs.paddingTop);
    const bottom = r.bottom - parseFloat(cs.borderBottomWidth) - parseFloat(cs.paddingBottom);
    let lo = Infinity, hi = -Infinity;
    const take = (b) => { if (b.height > 0 && b.width > 0) { lo = Math.min(lo, b.top); hi = Math.max(hi, b.bottom); } };
    const walk = (el) => {
      if (!el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return;
      if (el instanceof SVGSVGElement || el.children.length === 0 && !el.textContent.trim()) {
        take(el.getBoundingClientRect());
        return;
      }
      for (const n of el.childNodes) {
        if (n.nodeType === 3 && n.textContent.trim()) {
          const range = document.createRange();
          range.selectNodeContents(n);
          for (const b of range.getClientRects()) take(b);
        } else if (n.nodeType === 1) walk(n);
      }
    };
    walk(c);
    out[id] = { h: r.height, inner: bottom - top, span: hi > lo ? hi - lo : 0, top: lo - top, below: bottom - hi };
  }
  return out;
})()"""


def kiosk_fill_problems(pg: UIPage, exp: dict, size) -> list[str]:
    """W9d: the wall tablet is read from across the room. The cards' content fills
    them (larger type, no large empty bands); on a dry day the chart card is just
    its line and Now takes the space."""
    w, h = size
    cards, problems = pg.js(KIOSK_CARDS_JS), []
    for card, share in KIOSK_FILL.items():
        c = cards.get(card)
        if not c:
            problems.append(f"#{card} not visible in the kiosk view")
            continue
        if c["span"] < share * c["inner"]:
            problems.append(f"#{card}: its content spans {c['span']:.0f} px of the card's {c['inner']:.0f} px inner "
                            f"height at {w}x{h} ({c['top']:.0f} px empty above it, {c['below']:.0f} px below), "
                            f"at least {share:.0%}: larger type instead of empty bands")
    for hook, share in KIOSK_FONT_SHARE.items():
        els = [e for e in pg.ui(hook) if e["visible"]]
        if els and els[0]["fontSize"] < share * h - 0.5:
            problems.append(f"[data-test={hook}] font size {els[0]['fontSize']:.0f} px at {w}x{h}, "
                            f"at least {share * h:.0f} px ({share:.0%} of the screen height)")
    strip = pg.js('(() => { const s = document.getElementById("radar-strip"); '
                  'return s && s.checkVisibility() ? s.getBoundingClientRect().height : null; })()')
    if strip is not None and strip < KIOSK_RADAR_SHARE * h - 0.5:
        problems.append(f"the radar strip is {strip:.0f} px high at {w}x{h}, at least {KIOSK_RADAR_SHARE * h:.0f} px")
    chart = cards.get("chart-card")
    if exp.get("chart") == "dry" and chart and chart["h"] > KIOSK_DRY_CHART_MAX * h + 1:
        problems.append(f"#chart-card is {chart['h']:.0f} px high on a dry day at {w}x{h}, at most "
                        f"{KIOSK_DRY_CHART_MAX * h:.0f} px: just its line, Now takes the rest of the column")
    return problems


def _page_errors(pg: UIPage) -> list[str]:
    pg.p.pump()
    return [e for e in pg.p.errors if e.startswith("exception:")]


def refresh_render_error(browser, base, sc, lang) -> list[str]:
    """Malformed data that today's renderers can't draw: the radar steps and an
    accuracy row are null. The other parts must still render, nothing may
    throw uncaught, and the next page reload must still be scheduled."""
    pg = UIPage(browser, base, sc["now"], lang, fakes={
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


def refresh_config_retry(browser, base, sc, lang) -> list[str]:
    """/api/config fails once at startup (503): the page must try again by
    itself and show the place and the forecast within CONFIG_RETRY_S."""
    pg = UIPage(browser, base, sc["now"], lang, fakes={"/api/config": [(503, '{"detail": "unavailable"}')]})
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


def theme_toggle(browser, base, sc, lang, done) -> list[str]:
    pg = UIPage(browser, base, sc["now"], lang, scheme="dark")
    problems = theme_problems(pg.js("__ui.page()"), "dark")
    for step, want in (("first click", "light"), ("after reload", "light"), ("second click", "dark")):
        if step == "after reload":
            pg.reload()
        else:
            problems += pg.click("theme-toggle")
        lum = pg.js("__ui.page()")["bodyLum"] or 0
        if (want == "light") != (lum > 0.6):
            problems.append(f"system theme dark, {step}: expected the {want} theme, background luminance {lum:.2f}")
    done(pg)
    return problems


def run_wizard(browser, base, sc, lang, add, done, shot):
    pg = UIPage(browser, base, sc["now"], lang)
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
    if el and lang == "de" and re.search(r"\blatitude\b", el["text"], re.I):
        problems.append(f"German page, English message: {el['text']!r}")
    add("validation", problems)
    shot(pg, "setup-validation")
    done(pg)
    if lang != "en":
        return
    pg = UIPage(browser, base, sc["now"], lang)
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
    add("search", problems)
    problems = pg.type_into("setup-tz", "Europe/Berlin") + pg.click("setup-save")
    end = time.monotonic() + 20
    while time.monotonic() < end and not any(e["visible"] for e in pg.ui("rain-answer")):
        time.sleep(0.2)
        pg.p.pump()
    problems += visible_one(pg, "rain-answer")[1] + expect_hidden(pg, "setup")
    problems += expect_tokens(pg, "location", ["Alexanderplatz"])
    add("save", problems)
    shot(pg, "after-save")
    # the saved label is long: at 360 px it shows in full (wrapped, not cut off), coordinates below
    phone = UIPage(browser, base, sc["now"], lang, width=360, height=740)
    problems = expect_tokens(phone, "location", WIZARD_LABEL) + phone.js('__ui.clipped("location")')
    problems += expect_tokens(phone, "location-detail", WIZARD_DETAIL)
    info = phone.js("__ui.page()")
    if info["sw"] > 361:
        problems.append(f"page is {info['sw']} px wide at 360 px: {phone.js('__ui.overflowing()')}")
    add("location-long", problems)
    shot(phone, "after-save-phone-360")
    done(phone)
    problems = pg.click("location-button")
    problems += visible_one(pg, "setup")[1] + visible_one(pg, "setup-cancel")[1]
    if not problems:
        problems += pg.click("setup-cancel") + expect_hidden(pg, "setup") + visible_one(pg, "rain-answer")[1]
    add("change", problems)
    done(pg)


# --- unit tests, static files -------------------------------------------------

def run_unit(res: Results):
    for path in unit_files():
        r = subprocess.run(["node", "--test", str(path)], cwd=REPO, capture_output=True, text=True, timeout=120)
        out = r.stdout + r.stderr
        if r.returncode == 0:
            res.add(f"unit/{path.name}", [])
            continue
        lines = [l.strip() for l in out.splitlines()]
        failed = [l for l in lines if l.startswith("not ok")]
        detail = [l for l in lines if re.match(r"(error|expected|actual|code):", l) or "Error" in l][:6]
        res.add(f"unit/{path.name}", (failed[:6] + detail) or [out[-600:]])


def check_static(res: Results):
    files = sorted(STATIC.iterdir())
    total = sum(p.stat().st_size for p in files if p.is_file())
    res.add("budget", [] if total <= BUDGET_BYTES else
            [f"app/static is {total / 1024:.1f} KB, budget {BUDGET_BYTES // 1024} KB"])
    bad = [p.name for p in files if p.is_dir() or p.suffix not in ALLOWED_EXT]
    res.add("static-files", [f"{n}: the Rust app serves one flat directory of .html/.js/.css files only" for n in bad])


# --- main -----------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--binary", default="/target/debug/wetter", help="the Rust binary")
    ap.add_argument("--scenario", nargs="*", choices=UI_SCENARIOS, help="only these scenarios")
    ap.add_argument("--lang", nargs="*", choices=list(LOCALES), help="only these languages")
    ap.add_argument("--require", nargs="*", default=["*"],
                    help="check patterns that must pass (fnmatch, * crosses /); others are reported only")
    ap.add_argument("--shots", metavar="DIR", help="save screenshots there (for a design review)")
    ap.add_argument("--no-unit", action="store_true", help="skip the JS unit tests")
    ap.add_argument("--list", action="store_true", help="list the checks and exit")
    ap.add_argument("--backend-log", default=None, help="file for the app's output (default: discard)")
    args = ap.parse_args()
    scenarios = args.scenario or UI_SCENARIOS
    langs = args.lang or list(LOCALES)
    if args.list:
        print("\n".join(all_names(scenarios, langs)))
        return 0
    args.log = open(args.backend_log, "a") if args.backend_log else subprocess.DEVNULL
    if args.shots:
        pathlib.Path(args.shots).mkdir(parents=True, exist_ok=True)

    res = Results()
    check_static(res)
    if not args.no_unit:
        run_unit(res)
    browsers = {}
    try:
        for lang in langs:
            browsers[lang] = Browser(lang=LOCALES[lang])
        for name in scenarios:
            run_scenario(name, browsers, args, res)
    finally:
        for b in browsers.values():
            b.close()

    passed = failed = required_failed = 0
    expected = [n for n in all_names(scenarios, langs) if not (args.no_unit and n.startswith("unit/"))]
    for name in expected:
        problems = res.problems.get(name)
        if problems is None:
            problems = ["not checked (harness error before this check)"]
        if not problems:
            passed += 1
            print(f"PASS {name}")
            continue
        failed += 1
        required = any(fnmatch.fnmatch(name, p) for p in args.require)
        required_failed += required
        print(f"FAIL {name}{'' if required else ' (not required yet)'}")
        for p in problems[:8]:
            print(f"     {p}")
    print(f"uitest: {passed} passed, {failed} failed, {required_failed} of them required")
    return 1 if required_failed else 0


if __name__ == "__main__":
    sys.exit(main())
