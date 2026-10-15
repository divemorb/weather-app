"""The kiosk view and the big view: the chart filling its share, the cards filled,
the labels and the headline."""

from __future__ import annotations

import json

from expect import (BIG_HEADLINE_FILL, BIG_HEADLINE_LEAD, BIG_HEADLINE_LINES, BIG_HEADLINE_MAX,
                    BIG_HEADLINE_SIZES, BIG_HIERARCHY_SIZES, BIG_LABEL_GAP, BIG_PHONE,
                    BIG_PHONE_MIN_FONT, KIOSK_CHART_LABEL_PX, KIOSK_CHART_MIN,
                    KIOSK_CHART_MIN_W, KIOSK_DRY_CHART_MAX, KIOSK_FILL, KIOSK_FONT_SHARE,
                    KIOSK_RADAR_SHARE, KIOSK_REASON_SHARE, KIOSK_ROOM_FILL, KIOSK_ROOM_TOP,
                    TRACK_CONTRAST, VIEW_DESKTOP, VIEW_LABEL)
from page import Run, UIPage, norm, visible_one

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
    let lo = Infinity, hi = -Infinity, left = Infinity;
    const take = (b) => {
      if (b.height > 0 && b.width > 0) { lo = Math.min(lo, b.top); hi = Math.max(hi, b.bottom); left = Math.min(left, b.left); }
    };
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
    out[id] = { h: r.height, inner: bottom - top, span: hi > lo ? hi - lo : 0, top: lo - top, below: bottom - hi,
                left: left - r.left };
  }
  return out;
})()"""


def kiosk_room_problems(pg: UIPage, size) -> list[str]:
    """In the big view the glance's and Now's content start at the top of their cards
    and take the room (no empty band above them); Now's text keeps at least the glance's
    distance from the card's left border; the "why" line is read from across the room too."""
    w, h = size
    cards, problems = pg.js(KIOSK_CARDS_JS), []
    for card, share in KIOSK_ROOM_FILL.items():
        c = cards.get(card)
        if not c:
            problems.append(f"#{card} not visible in the big view")
            continue
        if c["top"] > KIOSK_ROOM_TOP * c["inner"] + 0.5:
            problems.append(f"#{card}: {c['top']:.0f} px empty above its content at {w}x{h}, at most "
                            f"{KIOSK_ROOM_TOP * c['inner']:.0f} px ({KIOSK_ROOM_TOP:.0%} of the card's "
                            f"{c['inner']:.0f} px inner height): the content starts at the top")
        if c["span"] < share * c["inner"] - 0.5:
            problems.append(f"#{card}: its content spans {c['span']:.0f} px of the card's {c['inner']:.0f} px inner "
                            f"height at {w}x{h} ({c['below']:.0f} px empty below it), at least {share:.0%}: "
                            "give the room to the content (larger type and spacing)")
    g, n = cards.get("glance"), cards.get("now")
    if g and n and n["left"] < g["left"] - 1:
        problems.append(f"#now's text starts {n['left']:.0f} px from the card's left border, #glance's "
                        f"{g['left']:.0f} px: at least as far as the glance's")
    els = [e for e in pg.ui("sky-reason") if e["visible"]]
    if not els:
        problems.append("[data-test=sky-reason] not visible in the big view")
    elif els[0]["fontSize"] < KIOSK_REASON_SHARE * h - 0.5:
        problems.append(f"[data-test=sky-reason] font size {els[0]['fontSize']:.0f} px at {w}x{h}, at least "
                        f"{KIOSK_REASON_SHARE * h:.0f} px ({KIOSK_REASON_SHARE:.1%} of the screen height): "
                        "the line that says why the sky looks as it does is read from across the room too")
    return problems


def big_label_problems(pg: UIPage, where: str) -> list[str]:
    """At least 3 radar time labels, all inside the card, none touching another."""
    labels = sorted((e for e in pg.ui("radar-label") if e["visible"]), key=lambda e: e["rect"]["x"])
    if len(labels) < 3:
        return [f"{where}: {len(labels)} visible [data-test=radar-label], expected at least 3"]
    problems = []
    for a, b in zip(labels, labels[1:]):
        gap = b["rect"]["x"] - a["rect"]["right"]
        if gap < BIG_LABEL_GAP:
            problems.append(f"{where}: radar labels {a['text']!r} and {b['text']!r} are {gap:.0f} px apart "
                            f"(overlapping when < 0), at least {BIG_LABEL_GAP} px")
    card = pg.js('(() => { const r = document.getElementById("glance").getBoundingClientRect(); '
                 'return {x: r.x, right: r.right}; })()')
    for e in labels:
        if e["rect"]["x"] < card["x"] - 0.5 or e["rect"]["right"] > card["right"] + 0.5:
            problems.append(f"{where}: radar label {e['text']!r} sticks out of #glance")
    return problems


def headline_lines(pg: UIPage) -> int:
    """The number of rendered lines the rain-answer headline takes on the page."""
    return pg.js("""(() => {
        const el = document.querySelector('[data-test="rain-answer"]');
        const range = document.createRange();
        range.selectNodeContents(el);
        return new Set([...range.getClientRects()].filter((r) => r.width > 0).map((r) => Math.round(r.bottom))).size;
    })()""")


def headline_problems(pg: UIPage, size) -> list[str]:
    """At most BIG_HEADLINE_LINES lines, at least BIG_PHONE_MIN_FONT, and as large as fits: at
    least BIG_HEADLINE_FILL of the largest whole-px size up to BIG_HEADLINE_MAX that keeps it to
    that many lines (tried on the page itself, the inline style restored afterwards)."""
    where = f"{size[0]}x{size[1]}"
    els = [e for e in pg.ui("rain-answer") if e["visible"]]
    if not els:
        return [f"{where}: [data-test=rain-answer] not visible"]
    font, lines = els[0]["fontSize"], headline_lines(pg)
    best = pg.js(f"""(() => {{
        const el = document.querySelector('[data-test="rain-answer"]');
        const saved = el.style.fontSize, range = document.createRange();
        const count = () => {{ range.selectNodeContents(el);
            return new Set([...range.getClientRects()].filter((r) => r.width > 0).map((r) => Math.round(r.bottom))).size; }};
        let best = 0;
        for (let px = {BIG_HEADLINE_MAX}; px >= 8; px--) {{
            el.style.fontSize = px + "px";
            if (count() <= {BIG_HEADLINE_LINES}) {{ best = px; break; }}
        }}
        el.style.fontSize = saved;
        return best;
    }})()""")
    problems = []
    text = repr(els[0]["text"])
    if lines > BIG_HEADLINE_LINES:
        problems.append(f"{where}: the headline {text} takes {lines} lines at {font:.0f} px, at most {BIG_HEADLINE_LINES}")
    if font < BIG_PHONE_MIN_FONT - 0.5:
        problems.append(f"{where}: the headline {text} is {font:.0f} px, at least {BIG_PHONE_MIN_FONT} px")
    if best and font < BIG_HEADLINE_FILL * best - 0.5:
        problems.append(f"{where}: the headline {text} is {font:.0f} px, but {best} px would still fit in "
                        f"{BIG_HEADLINE_LINES} lines (at most {BIG_HEADLINE_MAX} px tried): at least "
                        f"{BIG_HEADLINE_FILL * best:.0f} px, as large as the text allows")
    return problems


def hierarchy_problems(pg: UIPage, size) -> list[str]:
    """The big view's glance: the headline at least BIG_HEADLINE_LEAD times the radar line and
    the "why" line; the radar line at least as large as the "why" line."""
    where = f"{size[0]}x{size[1]}"
    fs = {}
    for hook in ("rain-answer", "rain-when", "sky-reason"):
        els = [e for e in pg.ui(hook) if e["visible"]]
        if els:
            fs[hook] = els[0]["fontSize"]
    if "rain-answer" not in fs:
        return [f"{where}: [data-test=rain-answer] not visible"]
    problems = []
    for hook in ("rain-when", "sky-reason"):
        if hook in fs and fs["rain-answer"] < BIG_HEADLINE_LEAD * fs[hook] - 0.5:
            problems.append(f"{where}: the headline is {fs['rain-answer']:.0f} px, [data-test={hook}] {fs[hook]:.0f} px: "
                            f"the headline must stay the largest line, at least {BIG_HEADLINE_LEAD}x the others")
    if "rain-when" in fs and "sky-reason" in fs and fs["rain-when"] < fs["sky-reason"] - 0.5:
        problems.append(f"{where}: [data-test=rain-when] ({fs['rain-when']:.1f} px) is smaller than the \"why\" line "
                        f"under it ({fs['sky-reason']:.1f} px): the radar line comes first, at least as large")
    return problems


def track_problems(pg: UIPage, theme: str, rain: bool = False) -> list[str]:
    """The empty radar tracks against the glass right above the strip (text made transparent,
    the sky standing still): the strip must be seen on a dry day too. rain=True: the empty
    part (top third) of the tracks under rainy columns instead."""
    strip = pg.js('(() => { const s = document.getElementById("radar-strip"); if (!s || !s.checkVisibility()) '
                  'return null; const r = s.getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height}; })()')
    if not strip:
        return [f"{theme}: the radar strip is not visible in the big view"]
    kind = "1" if rain else "0"
    cols = [e["rect"] for e in pg.ui("radar-step") if e["visible"] and e["attrs"].get("data-rain") == kind]
    if not cols:
        return [f"{theme}: no {'rainy' if rain else 'dry'} [data-test=radar-step] to measure"]
    inset = 0.25  # the middle of each track, away from its rounded corners (rainy: its empty top third)
    rects = [{"x": c["x"] + c["w"] * inset, "y": c["y"] + c["h"] * (0.1 if rain else inset),
              "w": c["w"] * (1 - 2 * inset), "h": c["h"] * (0.25 if rain else 1 - 2 * inset)} for c in cols]
    above = {"x": strip["x"], "y": strip["y"] - 8, "w": strip["w"], "h": 6}
    pg.js("__ui.hideText(true)")
    pg.frame()
    b64 = pg.shot_b64()
    pg.js("__ui.hideText(false)")
    meds = pg.js(f"__ui.medianIn({json.dumps(b64)}, {json.dumps(rects + [above])})")
    glass = meds[-1]
    if glass is None:
        return [f"{theme}: nothing measured above the radar strip"]

    def lum(rgb):
        c = [v / 255 for v in rgb]
        c = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    def ratio(a, b):
        la, lb = sorted((lum(a), lum(b)), reverse=True)
        return (la + 0.05) / (lb + 0.05)

    worst = min((ratio(m, glass), m) for m in meds[:-1] if m)
    if worst[0] + 1e-6 < TRACK_CONTRAST:
        hexc = lambda rgb: "#" + "".join(f"{v:02x}" for v in rgb)  # noqa: E731
        return [f"{theme}: an empty radar track{' under a rainy column' if rain else ''} ({hexc(worst[1])}) against the glass above the strip "
                f"({hexc(glass)}) is {worst[0]:.2f}:1, at least {TRACK_CONTRAST}:1: the strip must be seen"]
    return []


def run_big(run: Run):
    """The big view (the default) on a desktop and on a phone."""
    problems = []
    for size, where in ((VIEW_DESKTOP, "desktop"), (BIG_PHONE, "phone")):
        pg = run.page(width=size[0], height=size[1])
        problems += big_label_problems(pg, f"{where} {size[0]}x{size[1]}")
        pg.close()
    hp = []
    for size in BIG_HEADLINE_SIZES:
        pg = run.page(width=size[0], height=size[1])
        hp += headline_problems(pg, size)
        pg.close()
    run.add("big-headline", hp)
    order = []
    for size in BIG_HIERARCHY_SIZES:
        pg = run.page(width=size[0], height=size[1])
        order += hierarchy_problems(pg, size)
        pg.close()
    run.add("big-hierarchy", order)
    if "rain-tracks" in run.names:
        tracks = []
        for theme in ("light", "dark"):
            pg = run.page(width=VIEW_DESKTOP[0], height=VIEW_DESKTOP[1], scheme=theme, reduced=True)
            tracks += track_problems(pg, theme, rain=True)
            pg.close()
        run.add("rain-tracks", tracks)
    run.add("big-labels", problems)
    if "view-label" in run.names:
        problems = []
        for size in (VIEW_DESKTOP, BIG_PHONE):
            pg = run.page(width=size[0], height=size[1])
            for step, view in (("first load", "big"), ("after a click", "detailed")):
                if step != "first load":
                    problems += pg.click("view-toggle")
                el, p = visible_one(pg, "view-toggle")
                problems += [f"{size[0]} px, {step}: {x}" for x in p]
                if not el:
                    continue
                want = VIEW_LABEL[view][run.lang]
                if norm(el["text"]) != want:
                    problems.append(f"{size[0]} px, {view} view: the view button shows {el['text']!r}, expected "
                                    f"the text {want!r} (where a click goes; an icon alone read as 'pause')")
                if want.lower() not in el["name"].lower():
                    problems.append(f"{size[0]} px, {view} view: the view button's accessible name {el['name']!r} "
                                    f"must contain its visible text {want!r} (WCAG 2.5.3)")
                if el["rect"]["h"] > 2.2 * el["fontSize"] + 16:
                    problems.append(f"{size[0]} px, {view} view: the view button is {el['rect']['h']:.0f} px high: "
                                    "its text wraps, keep it on one line")
            info = pg.js("__ui.page()")
            if info["sw"] > size[0] + 1:
                problems.append(f"{size[0]} px: the page is {info['sw']} px wide: {pg.js('__ui.overflowing()')}")
            pg.close()
        run.add("view-label", problems)
    if "big-tracks" in run.names:
        problems = []
        for theme in ("light", "dark"):
            pg = run.page(width=VIEW_DESKTOP[0], height=VIEW_DESKTOP[1], scheme=theme, reduced=True)
            problems += track_problems(pg, theme)
            pg.close()
        run.add("big-tracks", problems)


def kiosk_fill_problems(pg: UIPage, exp: dict, size) -> list[str]:
    """The wall tablet is read from across the room. The cards' content fills
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
