"""Responsive (REQ_PAGE_14): any window from 360 px wide, any aspect ratio, resizing
and rotation. Each check loads its page once and resizes it through the sweep, the
rotations (the rainy big view also a slow drag) and back; after every resize, once
the layout holds still (polled), one probe (PROBE_JS) checks the invariants: no
horizontal scrolling, nothing outside its card, cut off or overlapping, readable text,
the headline the largest (two lines when narrow), axis labels apart, the station
map's names on no other name or symbol, the chart drawn 1:1 with four hours named,
the sky behind everything, a scrolled page keeping its place. Checks: responsive-big (the big view), responsive-details (the details page),
responsive-picker (the report picker open), responsive-wizard (the setup opened from
the place button), responsive-topbar (the top bar stays put when the view changes)."""

from __future__ import annotations

import dataclasses
import json
import pathlib
import time

from cdp import Browser
from expect import LOCALES

# the checks per scenario, and the page each one sweeps: (query, the button clicked first)
CHECKS = {"rain": ["responsive-big", "responsive-details"],
          "live": ["responsive-big", "responsive-details", "responsive-wizard", "responsive-topbar"],
          "errors": ["responsive-big", "responsive-details"],
          "accuracy": ["responsive-details"],
          "unconfigured": ["responsive-big"],
          "fallback": ["responsive-big"],
          "report": ["responsive-big", "responsive-picker"]}
PAGES = {"responsive-big": ("", None), "responsive-details": ("?detailed", None),
         "responsive-picker": ("", "report-open"), "responsive-wizard": ("", "location-button")}
DRAG_SCENARIOS = ("rain",)  # the slow drag: the rainy big view (the chart redrawn at every step)
WEBKIT_MIN_WIDTH = 447  # WebKitGTK's narrowest window: the sizes below it are left out there

# (width, height): widths 360-2560, aspect ratios 0.45-3.2; the user's devices and common
# screens are samples, never targets (every size must pass)
SWEEP = [(360, 640), (360, 800), (375, 667), (390, 844), (412, 915), (430, 932), (600, 900), (673, 841),
         (700, 500), (768, 1024), (800, 1280), (820, 1180), (1032, 1280), (1080, 1920), (844, 390), (915, 412),
         (932, 430), (1024, 600), (1024, 768), (1180, 820), (1280, 720), (1280, 800), (1366, 768), (1376, 940),
         (1440, 900), (1600, 600), (1920, 600), (1920, 1080), (2560, 1440)]
ROTATIONS = [((390, 844), (844, 390)), ((820, 1180), (1180, 820)), ((1032, 1280), (1376, 940))]
DRAG_WIDTHS = list(range(360, 1641, 80))  # a desktop window dragged from narrow to wide
DRAG_HEIGHT = 800
SETTLE_S = 1.5  # the layout must be still within this time after a resize
STILL_S = 0.12  # ... and stay still this long (several frames; the redraws follow within one)
TEXT_MIN = 12   # px, every text
FINE_MIN = 11   # px, the fine print (FINE_PRINT)
FINE_PRINT = ".attr, .now-fallback"
DISPLAY_NUMBERS = ["rain-probability", "now-temp"]  # may be larger than the headline
LABEL_ROWS = ['[data-test="chart-x-label"]', '#radar-labels > *']
LABEL_GAP = 2   # px between two neighbouring axis labels
MIN_HOURS = 4   # the 24 h chart names at least this many hours
NARROW_PX, HEADLINE_LINES = 640, 2  # narrower than 40em: the headline in at most two lines
# the top bar's parts that must not move or change size when the view changes (REQ_PAGE_3)
TOPBAR = [".topbar", "#location", '[data-test="location-button"]',
          '[data-test="view-toggle"]', '[data-test="theme-toggle"]']
TOPBAR_SLACK = 1  # px
# The type scale (REQ_PAGE_15): every text in one of these styles, each style one size at a
# given window in every view (the page's registered --t-<style> lengths on body), and the
# roles: which part uses which style.
TYPE_STYLES = ["large", "title2", "title3", "headline", "body", "subhead", "footnote", "caption"]
TYPE_ROLES = {
    "large": ['[data-test="rain-probability"]'],
    "title2": ['[data-test="rain-answer"]', '[data-test="now-temp"]', ".now-condition"],
    "title3": [".refresh-value"],
    "headline": [".place", "#view-toggle", ".now-value"],
    "body": [".glance-when", ".glance-reason", ".detail-line", ".source-row", ".obs-row", ".chart-status"],
    "subhead": [".glance-prob-label", ".now-label", ".chart-legend-item"],
    "footnote": [".glance-title", ".now-title", ".chart-title", ".details-title", ".details-section h3", ".radar-caption",
                 ".now-time", ".now-station"],
    "caption": [".radar-labels > *", '[data-test="chart-x-label"]', ".attr"],
}

# One probe: every invariant at the current size; [invariant, detail] pairs (responsive_probe.js).
PROBE_JS = (pathlib.Path(__file__).resolve().parent / "responsive_probe.js").read_text()

# What must hold still before a size is measured: the page size, the cards' boxes, the
# headline's size, the chart's drawn size (a redraw after the resize changes it).
SIGNATURE_JS = r"""(() => {
  const de = document.documentElement;
  const r = (el) => { const b = el.getBoundingClientRect(); return b.width === 0 ? [] : [Math.round(b.left), Math.round(b.top + scrollY), Math.round(b.width), Math.round(b.height)]; };
  const a = document.querySelector('[data-test="rain-answer"]');
  const svg = document.querySelector('[data-test="chart"]');
  return JSON.stringify([de.clientWidth, de.clientHeight, de.scrollWidth, de.scrollHeight,
    [...document.querySelectorAll(".wrap .card")].map(r), a ? getComputedStyle(a).fontSize : "",
    svg ? svg.getAttribute("viewBox") : ""]);
})()"""

CFG = json.dumps({"fine": FINE_PRINT, "fineMin": FINE_MIN, "textMin": TEXT_MIN, "display": DISPLAY_NUMBERS,
                  "rows": LABEL_ROWS, "gap": LABEL_GAP, "minHours": MIN_HOURS,
                  "narrow": NARROW_PX, "lines": HEADLINE_LINES,
                  "styles": TYPE_STYLES, "roles": TYPE_ROLES})


def settle(pg) -> float | None:
    """Wait until the layout holds still for STILL_S (polled); the seconds it took, or None
    when it was still moving after SETTLE_S."""
    start = time.monotonic()
    last, since = None, start
    while True:
        pg.frame()
        sig = pg.js(SIGNATURE_JS)
        now = time.monotonic()
        if sig != last:
            last, since = sig, now
        elif now - since >= STILL_S:
            return since - start
        if now - start > SETTLE_S:
            return None
        time.sleep(0.04)


# A page that scrolls keeps the reader's place when the layout is fitted again (a content
# update, a resize event): scrolled halfway, a resize event of the same size changes nothing.
SCROLL_KEPT_JS = r"""(async () => {
  const se = document.scrollingElement, half = Math.floor((se.scrollHeight - se.clientHeight) / 2);
  if (half < 50) return null;
  se.scrollTop = half;
  window.dispatchEvent(new Event("resize"));
  for (let i = 0; i < 3; i++) await new Promise((r) => requestAnimationFrame(r));
  const at = se.scrollTop;
  se.scrollTop = 0;
  return Math.abs(at - half) > 1 ? "scrolled to " + half + " px, after a refit at " + at + " px" : null;
})()"""


def measure(pg, w: int, h: int, what: str) -> list[str]:
    """Resize to w x h, wait for the layout, and return the broken invariants."""
    pg.p.resize(w, h)
    took = settle(pg)
    problems = [] if took is not None else [f"{what} {w}x{h}: still moving {SETTLE_S} s after the resize"]
    problems += [f"{what} {w}x{h}: {inv}: {detail}" for inv, detail in pg.js(f"{PROBE_JS}({CFG})")]
    moved = pg.js(SCROLL_KEPT_JS)
    return problems + ([f"{what} {w}x{h}: scroll-kept: {moved}"] if moved else [])


def sweep_page(run, query: str = "", drag: bool = True, min_width: int = 360,
               click: str | None = None) -> dict[str, list[str]]:
    """One page (``query``: the view; ``click``: a button's data-test hook clicked first,
    e.g. the report picker) through the sweep, the rotations, the drag and back to the
    first size; problems per part: "sweep", "turn", "drag", "back"."""
    first = SWEEP[0] if SWEEP[0][0] >= min_width else next(s for s in SWEEP if s[0] >= min_width)
    pg = run.page(width=first[0], height=first[1], query=query)
    out = {"sweep": [], "turn": [], "drag": [], "back": []}
    try:
        if click:
            out["sweep"] += [f"before the sweep: {p}" for p in pg.click(click)]
        settle(pg)
        fresh = pg.js(SIGNATURE_JS)
        for w, h in SWEEP:
            if w >= min_width:
                out["sweep"] += measure(pg, w, h, "size")
        for a, b in ROTATIONS:
            if min(a[0], b[0]) >= min_width:
                for w, h in (a, b, a):
                    out["turn"] += measure(pg, w, h, f"turned {a[0]}x{a[1]}")
        if drag:
            for w in DRAG_WIDTHS:
                if w >= min_width:
                    out["drag"] += measure(pg, w, DRAG_HEIGHT, "dragged to")
        pg.p.resize(*first)
        settle(pg)
        back = pg.js(SIGNATURE_JS)
        if back != fresh:
            out["back"].append(f"back at {first[0]}x{first[1]} after the sweep the layout differs from a fresh load: "
                               f"{back} vs {fresh}")
    finally:
        run.done(pg)
    return out


# The view and the top bar's boxes (page coordinates: left, top, width, height) per TOPBAR selector.
TOPBAR_JS = r"""((sels) => [document.documentElement.dataset.view, sels.map((s) => {
  const el = document.querySelector(s), b = el && el.getBoundingClientRect();
  return b ? [b.left + scrollX, b.top + scrollY, b.width, b.height] : null;
})])(%s)"""


def topbar_moves(size: str, states: list) -> list[str]:
    """The top bar's parts that differ between the first state and the others."""
    (view0, boxes0), out = states[0], []
    for view, boxes in states[1:]:
        moved = [f"{sel} {_box(a)} in the {view0} view, {_box(b)} in the {view} view"
                 for sel, a, b in zip(TOPBAR, boxes0, boxes)
                 if (a is None) != (b is None) or a and any(abs(x - y) > TOPBAR_SLACK for x, y in zip(a, b))]
        if moved:
            out.append(f"size {size}: the top bar moves: " + "; ".join(moved))
    return out


def _box(b) -> str:
    return "missing" if b is None else "{:.0f},{:.0f} {:.0f}x{:.0f}".format(*b)


def toggle_view(pg) -> list[str]:
    """A real click on the view button, then the layout settled (the bar's own data is
    there already: no wait for the network, unlike UIPage.click)."""
    at = pg.js("""(() => { const b = document.querySelector('[data-test="view-toggle"]').getBoundingClientRect(),
      x = b.left + b.width / 2, y = b.top + b.height / 2, top = document.elementFromPoint(x, y);
      return top && top.closest('[data-test="view-toggle"]') ? [x, y] : null; })()""")
    if not at:
        return ["the view button is covered or outside the window"]
    pg.p.mouse_click(*at)
    return [] if settle(pg) is not None else [f"still moving {SETTLE_S} s after the click"]


def topbar_page(run, min_width: int) -> list[str]:
    """At every sweep size the top bar before and after a click on the view button (no
    reload; the views alternate, so both directions are seen): every part in the same
    place and size, within TOPBAR_SLACK. Chromium shows classic scrollbars here, as a
    desktop does: a view that scrolls must not narrow the bar."""
    own = None if getattr(run.args, "browser", "chromium") == "webkit" else Browser(LOCALES[run.lang], scrollbars=True)
    run = dataclasses.replace(run, browser=own) if own else run
    sizes = [s for s in SWEEP if s[0] >= min_width]
    pg = run.page(width=sizes[0][0], height=sizes[0][1])
    js, problems = TOPBAR_JS % json.dumps(TOPBAR), []
    try:
        for w, h in sizes:
            pg.p.resize(w, h)
            settle(pg)
            states = [pg.js(js)]
            problems += [f"size {w}x{h}: {p}" for p in toggle_view(pg)]
            states.append(pg.js(js))
            if {v for v, _ in states} != {"big", "detailed"}:
                problems.append(f"size {w}x{h}: the view button switched {' -> '.join(v for v, _ in states)}")
            problems += topbar_moves(f"{w}x{h}", states)
    finally:
        run.done(pg)
        if own:
            own.close()
    return problems


def run_responsive(run) -> None:
    """The scenario's responsive checks that this run wants (CHECKS), each on its own page."""
    min_width = WEBKIT_MIN_WIDTH if getattr(run.args, "browser", "chromium") == "webkit" else 360
    for check in CHECKS.get(run.name, []):
        if check not in run.names:
            continue
        if check == "responsive-topbar":
            run.add(check, topbar_page(run, min_width))
            continue
        query, click = PAGES[check]
        drag = check == "responsive-big" and run.name in DRAG_SCENARIOS
        out = sweep_page(run, query, drag=drag, min_width=min_width, click=click)
        run.add(check, [p for part in out.values() for p in part])
