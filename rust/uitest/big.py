"""The big view: its labels, the headline (lines, size, lead) and the radar tracks."""

from __future__ import annotations

import json

from expect import (BIG_HEADLINE_LEAD, BIG_HEADLINE_LINES,
                    BIG_HEADLINE_SIZES, BIG_HIERARCHY_SIZES, BIG_LABEL_GAP, BIG_PHONE,
                    BIG_PHONE_MIN_FONT, TRACK_CONTRAST, VIEW_DESKTOP, VIEW_LABEL)
from page import Run, UIPage, norm, visible_one


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
    """At most BIG_HEADLINE_LINES lines, at least BIG_PHONE_MIN_FONT (its size is the type
    scale's title2 on every page: the responsive sweep's type-roles)."""
    where = f"{size[0]}x{size[1]}"
    els = [e for e in pg.ui("rain-answer") if e["visible"]]
    if not els:
        return [f"{where}: [data-test=rain-answer] not visible"]
    font, lines = els[0]["fontSize"], headline_lines(pg)
    problems = []
    text = repr(els[0]["text"])
    if lines > BIG_HEADLINE_LINES:
        problems.append(f"{where}: the headline {text} takes {lines} lines at {font:.0f} px, at most {BIG_HEADLINE_LINES}")
    if font < BIG_PHONE_MIN_FONT - 0.5:
        problems.append(f"{where}: the headline {text} is {font:.0f} px, at least {BIG_PHONE_MIN_FONT} px")
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


def big_label_pages(run: Run) -> list[str]:
    """The big view's radar labels, on a desktop and on a phone."""
    problems = []
    for size, where in ((VIEW_DESKTOP, "desktop"), (BIG_PHONE, "phone")):
        pg = run.page(width=size[0], height=size[1])
        problems += big_label_problems(pg, f"{where} {size[0]}x{size[1]}")
        pg.close()
    return problems


def run_big(run: Run):
    """The big view (the default) on a desktop and on a phone; a job that wants
    only the tracks (``rain-tracks``) loads no other big-view page."""
    if "big-labels" in run.names:
        run.add("big-labels", big_label_pages(run))
    if "big-headline" in run.names:
        hp = []
        for size in BIG_HEADLINE_SIZES:
            pg = run.page(width=size[0], height=size[1])
            hp += headline_problems(pg, size)
            pg.close()
        run.add("big-headline", hp)
    if "big-hierarchy" in run.names:
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
