"""Responsive (REQ_PAGE_14): any window from 360 px wide, any aspect ratio, resizing
and rotation. Each check loads its page once and resizes it through the sweep, the
rotations (the rainy big view also a slow drag) and back; after every resize, once
the layout holds still (polled), one probe (PROBE_JS) checks the invariants: no
horizontal scrolling, nothing outside its card, cut off or overlapping, readable text,
the headline the largest (two lines when narrow), axis labels apart, the chart drawn
1:1 with four hours named, the sky behind everything, a scrolled page keeping its
place. Checks: responsive-big (the big view), responsive-details (the details page),
responsive-picker (the report picker open), responsive-wizard (the setup opened from
the place button)."""

from __future__ import annotations

import json
import time

# the checks per scenario, and the page each one sweeps: (query, the button clicked first)
CHECKS = {"rain": ["responsive-big", "responsive-details"],
          "live": ["responsive-big", "responsive-details", "responsive-wizard"],
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

# One probe: every invariant at the current size; [invariant, detail] pairs.
PROBE_JS = r"""((cfg) => {
  const out = [];
  const de = document.documentElement, W = de.clientWidth, H = de.clientHeight;
  const vis = (el) => el.checkVisibility({ visibilityProperty: true, opacityProperty: true });
  const name = (el) => (el.dataset && el.dataset.test ? "[data-test=" + el.dataset.test + "]"
    : el.id ? "#" + el.id : el.tagName.toLowerCase() + (typeof el.className === "string" && el.className
      ? "." + el.className.trim().split(/\s+/)[0] : ""));
  const box = (r) => Math.round(r.left) + "," + Math.round(r.top) + " to " + Math.round(r.right) + "," + Math.round(r.bottom);
  if (de.scrollWidth > W + 1) out.push(["h-scroll", "the page is " + de.scrollWidth + " px wide in a " + W + " px window"]);
  for (const el of [de, document.body]) {
    const o = getComputedStyle(el).overflowY;
    if (el.scrollHeight > H + 1 && (o === "hidden" || o === "clip"))
      out.push(["cut-off", name(el) + " has overflow-y " + o + " but is " + el.scrollHeight + " px high in a " + H + " px window"]);
  }
  const sky = document.getElementById("sky");
  if (sky) {
    const r = sky.getBoundingClientRect();
    if (r.left > 0.5 || r.top > 0.5 || r.right < W - 0.5 || r.bottom < H - 0.5)
      out.push(["sky", "the sky covers " + box(r) + ", not the " + W + "x" + H + " window"]);
  }
  const cards = [...document.querySelectorAll(".wrap .card, .topbar, .wrap > .attr")].filter(vis)
    .filter((c) => !c.parentElement.closest(".card"));
  const rects = cards.map((c) => c.getBoundingClientRect());
  cards.forEach((c, i) => {
    const r = rects[i];
    if (r.width === 0 || r.height === 0) return;
    if (r.left < -1 || r.right > W + 1) out.push(["outside", name(c) + " (" + box(r) + ") outside the " + W + " px window"]);
    for (let j = i + 1; j < cards.length; j++) {
      const q = rects[j];
      const ox = Math.min(r.right, q.right) - Math.max(r.left, q.left), oy = Math.min(r.bottom, q.bottom) - Math.max(r.top, q.top);
      if (ox > 1 && oy > 1) out.push(["overlap", name(c) + " (" + box(r) + ") over " + name(cards[j]) + " (" + box(q) + ")"]);
    }
    const scrollers = [...c.querySelectorAll("*")].filter((el) => /auto|scroll/.test(getComputedStyle(el).overflowX));
    for (const el of c.querySelectorAll("*")) {  // a scroll box's content may be wider: it scrolls
      if (!vis(el) || el.closest("svg") && el.tagName.toLowerCase() !== "svg") continue;
      if (scrollers.some((s) => s !== el && s.contains(el))) continue;
      const b = el.getBoundingClientRect();
      if (b.width === 0 || b.height === 0) continue;
      if (b.left < r.left - 1 || b.top < r.top - 1 || b.right > r.right + 1 || b.bottom > r.bottom + 1) {
        out.push(["spill", name(el) + " (" + box(b) + ") reaches outside " + name(c) + " (" + box(r) + ")"]);
        break;
      }
    }
    for (const el of c.querySelectorAll("*")) {  // inside a clipping box but beyond it: cut off
      if (!vis(el) || el.closest("svg")) continue;
      const o = getComputedStyle(el);
      if (!/hidden|clip/.test(o.overflowX + o.overflowY)) continue;
      if (el.scrollHeight > el.clientHeight + 1 && /hidden|clip/.test(o.overflowY) ||
          el.scrollWidth > el.clientWidth + 1 && /hidden|clip/.test(o.overflowX))
        out.push(["clipped", name(el) + " cuts off its content (" + el.scrollWidth + "x" + el.scrollHeight
                  + " in " + el.clientWidth + "x" + el.clientHeight + ")"]);
    }
  });
  const answerEl = document.querySelector('[data-test="rain-answer"]');
  const answer = answerEl && vis(answerEl) ? parseFloat(getComputedStyle(answerEl).fontSize) : 0;
  const display = cfg.display.map((h) => document.querySelector('[data-test="' + h + '"]')).filter(Boolean);
  const walker = document.createTreeWalker(document.querySelector(".wrap") || document.body, NodeFilter.SHOW_TEXT);
  const small = [], larger = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const el = n.parentElement;
    if (!n.textContent.trim() || !el || !vis(el)) continue;
    let px = parseFloat(getComputedStyle(el).fontSize);
    const svg = el.closest("svg");
    if (svg) {
      const vb = svg.viewBox && svg.viewBox.baseVal;
      if (vb && vb.width) px *= svg.getBoundingClientRect().width / vb.width;
    }
    const min = el.closest(cfg.fine) ? cfg.fineMin : cfg.textMin;
    if (px < min - 0.05) small.push(name(el) + " " + px.toFixed(1) + " px (at least " + min + ")");
    if (answer && px > answer + 0.05 && el !== answerEl && !display.some((d) => d.contains(el)))
      larger.push(name(el) + " " + px.toFixed(1) + " px");
  }
  if (small.length) out.push(["text-size", small.length + " texts too small: " + [...new Set(small)].slice(0, 4).join("; ")]);
  if (larger.length) out.push(["hierarchy", "the headline is " + answer.toFixed(1) + " px, larger: " + [...new Set(larger)].slice(0, 3).join("; ")]);
  if (answer && W < cfg.narrow) {  // the user's rule: a narrow page's headline in at most two lines
    const range = document.createRange();
    range.selectNodeContents(answerEl);
    const lines = new Set([...range.getClientRects()].filter((r) => r.width > 0).map((r) => Math.round(r.bottom))).size;
    if (lines > cfg.lines) out.push(["headline-lines", "the headline takes " + lines + " lines in a " + W + " px window, at most " + cfg.lines]);
  }
  for (const sel of cfg.rows) {
    const rs = [...document.querySelectorAll(sel)].filter(vis).map((e) => e.getBoundingClientRect())
      .filter((r) => r.width > 0).sort((a, b) => a.left - b.left);
    for (let i = 1; i < rs.length; i++) {
      if (rs[i].left < rs[i - 1].right + cfg.gap && Math.abs(rs[i].top - rs[i - 1].top) < rs[i].height) {
        out.push(["labels", sel + ": two labels " + Math.round(rs[i - 1].right - rs[i].left + cfg.gap) + " px too close"]);
        break;
      }
    }
  }
  for (const svg of document.querySelectorAll('svg[data-test="chart"]')) {  // drawn 1:1, never scaled
    const vb = svg.viewBox.baseVal, r = svg.getBoundingClientRect();
    if (vis(svg) && (Math.abs(vb.width - r.width) > 1 || Math.abs(vb.height - r.height) > 1))
      out.push(["chart-scale", "the chart is drawn at " + vb.width + "x" + vb.height + " but shown at "
                + Math.round(r.width) + "x" + Math.round(r.height) + " (not redrawn for its box)"]);
  }
  const hours = [...document.querySelectorAll('[data-test="chart-x-label"]')].filter(vis).length;
  const chart = document.querySelector('svg[data-test="chart"]');
  if (chart && vis(chart) && hours < cfg.minHours)
    out.push(["chart-hours", "the chart shows " + hours + " hour labels, at least " + cfg.minHours]);
  for (const c of __ui.controls()) out.push(["buttons", c]);
  const ctrls = [...document.querySelectorAll("button, [role='button'], a[href], input, select")]
    .filter((el) => vis(el) && !el.closest("[inert]"))  // an inert control (under the open picker) can't be used
    .map((el) => [el, el.getBoundingClientRect()]).filter(([, r]) => r.width > 0 && r.height > 0);
  overlap: for (let i = 0; i < ctrls.length; i++) {  // no control lies over another
    for (let j = i + 1; j < ctrls.length; j++) {
      const [a, r] = ctrls[i], [b, q] = ctrls[j];
      if (a.contains(b) || b.contains(a)) continue;
      if (Math.min(r.right, q.right) - Math.max(r.left, q.left) > 1 && Math.min(r.bottom, q.bottom) - Math.max(r.top, q.top) > 1) {
        out.push(["controls-overlap", name(a) + " (" + box(r) + ") over " + name(b) + " (" + box(q) + ")"]);
        break overlap;
      }
    }
  }
  return out;
})(%s)"""

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
                  "narrow": NARROW_PX, "lines": HEADLINE_LINES})


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
    problems += [f"{what} {w}x{h}: {inv}: {detail}" for inv, detail in pg.js(PROBE_JS % CFG)]
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


def run_responsive(run) -> None:
    """The scenario's responsive checks that this run wants (CHECKS), each on its own page."""
    min_width = WEBKIT_MIN_WIDTH if getattr(run.args, "browser", "chromium") == "webkit" else 360
    for check in CHECKS.get(run.name, []):
        if check not in run.names:
            continue
        query, click = PAGES[check]
        drag = check == "responsive-big" and run.name in DRAG_SCENARIOS
        out = sweep_page(run, query, drag=drag, min_width=min_width, click=click)
        run.add(check, [p for part in out.values() for p in part])
