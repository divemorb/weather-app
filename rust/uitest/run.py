#!/usr/bin/env python3
"""UI contract: the web page in headless Chromium against the Rust app.

Per scenario (the contract suite's: recorded Berlin data, fake upstream,
frozen server clock) the Rust app is started; headless Chromium loads the
page in English (en-US) and German (de-DE), with the browser clock frozen
at the scenario's "now" (it runs on from there) and the browser in UTC, so
times must be shown in the location's time zone. The checks read what the
page shows through stable ``data-test`` hooks: content, not layout (see
``qwen/web/00_brief.md``, "UI contract"). Generic checks: no console errors
or CSP violations, same-origin requests only, contrast (WCAG AA) in both
themes, no horizontal overflow at 360 px, the kiosk view without
scrolling, control sizes, reduced motion, the size budget. The JS unit
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
    ANSWER, ATTRIBUTION_LINKS, BUDGET_BYTES, FIXED, KIOSK_MIN_FONT, KIOSK_SIZES, LOCALES, MODEL_LABELS,
    NOW, SCENARIO, SOURCES, TZ, WEIGHTS, WHEN, WIZARD_DETAIL, WIZARD_LABEL)
from fakeup import FakeUpstream  # noqa: E402
from scenarios import SCENARIOS  # noqa: E402

PROBE = (HERE / "probe.js").read_text()
ALLOWED_EXT = {".html", ".js", ".css"}

# --- the list of checks (also what --list prints) ---------------------------

COMMON = ["console", "requests", "lang", "location", "location-detail", "theme-light", "theme-dark", "theme-icon",
          "contrast-light", "contrast-dark", "overflow-360", "buttons", "attribution"]
GLANCE = ["rain-answer", "rain-when", "rain-probability"]
RADAR = ["radar-steps", "radar-labels"]
NOW_CHECKS = list(NOW)
CHART = ["chart-svg", "chart-series", "chart-legend", "chart-y-labels", "chart-x-labels", "chart-unit", "chart-dry"]
DETAILS = ["details-closed", "details-weights", "details-signals", "countdown-radar", "countdown-models",
           "countdown-page", "source-rows", "source-errors", "accuracy-table"]
KIOSK = [f"kiosk-{w}x{h}" for w, h in KIOSK_SIZES]


def check_names(scenario: str, lang: str) -> list[str]:
    if scenario in ("live", "rain"):
        names = COMMON + GLANCE + RADAR + NOW_CHECKS + CHART + DETAILS + KIOSK
        if scenario == "live":
            names = [n for n in names if not n.startswith("chart-") or n == "chart-dry"]
            names += ["theme-toggle"] if lang == "en" else []
        else:
            names += ["reduced-motion"] if lang == "en" else []
        return names
    if scenario == "errors":
        return (COMMON + ["rain-answer", "rain-when", "rain-probability", "radar-unavailable", "now-unavailable",
                          "chart-unavailable"] + [n for n in DETAILS if n not in ("details-weights", "details-signals")])
    if scenario == "accuracy":
        return ["console", "requests", "location", "location-detail", "rain-probability", "details-closed",
                "accuracy-table"]
    if scenario == "unconfigured":
        return ["console", "requests", "lang", "setup-visible", "theme-light", "theme-dark", "theme-icon",
                "contrast-light", "contrast-dark", "overflow-360", "buttons"]
    if scenario == "wizard":
        return ["console", "validation"] if lang == "de" else ["console", "requests", "validation", "search",
                                                               "save", "location-long", "change"]
    raise ValueError(scenario)


UI_SCENARIOS = ["live", "rain", "errors", "accuracy", "unconfigured", "wizard"]
SCENARIO_LANGS = {"wizard": ["de", "en"]}  # the German validation runs before the English save


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
                 reduced=False, query=""):
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
    r = pg.js("__ui.contrast()")
    if r["checked"] == 0:
        return ["no visible text found"]
    return r["bad"]


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
            up = SOURCES.get(e["attrs"].get("data-source"), "")
            if up and up not in e["text"]:
                problems.append(f"source row {e['attrs'].get('data-source')}: {e['text']!r} lacks {up!r}")
        add("source-rows", problems)
    if "source-errors" in names:
        n = sum(e["visible"] for e in pg.ui("source-error"))
        want = exp.get("source_errors", 0)
        add("source-errors", [] if n == want else [f"{n} visible [data-test=source-error], expected {want}"])
    if "accuracy-table" in names:
        add("accuracy-table", accuracy_problems(pg, exp))


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
    hooks = ["rain-answer", "rain-probability", "now-temp", "radar-step"] + (["chart-dry"] if exp["chart"] == "dry" else ["chart"])
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
    sc = next(s for s in SCENARIOS if s["name"] == name)
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
            else:
                add("now-unavailable", expect_text(pg, "now-unavailable", FIXED["now.unavailable"][lang])
                    + expect_hidden(pg, "now-temp"))
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
    if name in ("live", "rain", "errors", "unconfigured"):
        # C: phone, 360 px, everything opened
        pg = UIPage(browser, base, sc["now"], lang, width=360, height=740)
        pg.js("__ui.openDetails()")
        pg.settle()
        info = pg.js("__ui.page()")
        add("overflow-360", [] if info["sw"] <= 361 and info["iw"] <= 361 else
            [f"page is {info['sw']} px wide at 360 px (horizontal scrolling): {pg.js('__ui.overflowing()')}"])
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
            shot(pg, f"kiosk-{size[0]}x{size[1]}", full=False)
            done(pg)
    if "theme-toggle" in names:
        add("theme-toggle", theme_toggle(browser, base, sc, lang, done))
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
