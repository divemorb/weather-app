"""The page under test (headless Chromium via cdp): the probe, the frozen clock,
and the small text helpers."""

from __future__ import annotations

import math
import pathlib
import re

from expect import (LOCALES, MAP_BEARING_TOLERANCE, MAP_MARKS, MAP_RADIUS_KM, OBS_STATIONS,
                    TZ)

PROBE = (pathlib.Path(__file__).resolve().parent / "probe.js").read_text()

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


# --- the observation stations (the station list and the schematic map) -----------------

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
        return problems + [f"[data-test=station-map] data-station {sorted(got)}, expected {sorted(MAP_MARKS)} "
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
                 reduced=False, query="", fakes=None):
        """query: "" (the default big view: the content checks), "?detailed" (P2, phone test
        2026-10-12: the details page, only the Details card, open) or "?kiosk"."""
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

