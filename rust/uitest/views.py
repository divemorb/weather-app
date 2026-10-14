"""The views (big / detailed): the default big view, the view toggle and the
view query, the phone view, the detailed-only page, and the now fallback marks."""

from __future__ import annotations

from expect import VIEW_DESKTOP, VIEW_LABEL, VIEW_PHONE
from page import UIPage, expect_hidden, has, norm, visible_one
from page_checks import details_open_problems


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
    pg = UIPage(browser, base, sc["now"], lang, width=w, height=h, query="?detailed")
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
    problems = []
    for w, h in (VIEW_DESKTOP, (360, 740)):
        pg = UIPage(browser, base, sc["now"], lang, width=w, height=h, query="?detailed")
        problems += [f"{w}x{h}: {p}" for p in details_only_problems(pg, lang, w)]
        pg.close()
    add("view-details-only", problems)


def details_only_problems(pg: UIPage, lang: str, w: int) -> list[str]:
    """P2 (phone test, 2026-10-12): the detailed view is the details page: the Details
    card open; no place, glance, Now (so no report turn) or 24 hours; the top bar keeps
    its buttons, the view button leads back to the big view."""
    shown = pg.js("""Object.fromEntries(['glance', 'now', 'chart-card', 'location', 'location-detail']
      .map((id) => [id, !!document.getElementById(id)?.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })]))""")
    problems = [f"#{k} is visible on the details page" for k, v in shown.items() if v]
    problems += [p for hook in ("details", "view-toggle", "location-button", "theme-toggle")
                 for p in visible_one(pg, hook)[1]]
    problems += [p for p in details_open_problems(pg) if "source-row" not in p]
    el = (pg.ui("view-toggle") or [{}])[0]
    if norm(el.get("text")) != VIEW_LABEL["detailed"][lang]:
        problems.append(f"view-toggle shows {el.get('text')!r}, expected {VIEW_LABEL['detailed'][lang]!r}")
    info = pg.js("__ui.page()")
    if info["sw"] > w + 1:
        problems.append(f"page is {info['sw']} px wide: {pg.js('__ui.overflowing()')}")
    return problems


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