"""UI checks for the user reports.

The tile with ``data-report-host`` turns over: its ``report-open`` button shows
the back (``report-back``) with the picker; a tap saves the report
(``POST /api/reports``) and turns the tile back, whose front then shows
``report-line`` with ``report-undo``. The sky follows a fresh report
(``GET /api/reports/current``) and the "why" line names it; Details scores
the models against the reports. Nothing here names ``#now``: the host is found
by its attribute, and the ``report-glance`` scenario moves it to the glance.
"""
from __future__ import annotations

import json
import re
import shutil
import time
import urllib.request
from datetime import datetime, timedelta, timezone

from expect import (MODEL_LABELS, REPORT_FIT, REPORT_INTENSITY, REPORT_KIND_LABEL,
                    REPORT_KINDS, REPORT_MIN_BUTTON, REPORT_SAVE_S, REPORT_SCENE_KIND,
                    REPORT_SKY_CASES, REPORT_TEXT, REPORT_WHEN, SCENE_LABEL)
from page import has, norm
from page_checks import contrast_problems

LANG_I = {"en": 0, "de": 1}

# the flip and the picker; saving; the sky; Details.
FLIP = (["report-open", "report-closed", "report-flip", "report-picker", "report-shows", "report-close",
         "report-escape", "report-locked", "report-motion", "report-still", "report-buttons",
         "report-contrast-light", "report-contrast-dark", "report-open-clear"] + [f"report-fit-{v}" for v in REPORT_FIT])
SAVE = ["report-save", "report-undo", "report-undo-failed", "report-intensity", "report-skip", "report-confirm",
        "report-error", "report-line-fresh"]
SKY = [f"sky-report-{c}" for c in REPORT_SKY_CASES] + ["sky-report-none", "sky-after-save"]
DETAILS = ["details-reports", "details-reports-fit"]
GLANCE_HOST = ["report-open", "report-closed", "report-flip", "report-fit-big-1280x800", "report-fit-phone-360",
               "report-open-clear", "report-save", "report-undo"]


def check_names(scenario: str, lang: str) -> list[str]:
    """The checks a report scenario runs (report and report-glance)."""
    if scenario == "report":
        return ["console", "requests"] + FLIP + SAVE + SKY + DETAILS + ["report-night"]
    if scenario == "report-glance":
        return ["console"] + GLANCE_HOST
    raise ValueError(scenario)


def static_copy(src, dest) -> None:
    """app/static with data-report-host moved to the glance (the report-glance scenario)."""
    shutil.copytree(src, dest)
    index = dest / "index.html"
    html = re.sub(r'\s+data-report-host(="[^"]*")?', "", index.read_text())
    html, n = re.subn(r'(<section\b[^>]*\bid="glance")', r"\1 data-report-host", html, count=1)
    if n != 1:
        raise RuntimeError("no <section id=\"glance\"> in index.html")
    index.write_text(html)


# --- the backend, read and cleaned directly ----------------------------------

def _api(base: str, method: str, path: str):
    req = urllib.request.Request(base + path, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, None


def current(base: str):
    """The currently saved report (GET /api/reports/current), or None."""
    status, body = _api(base, "GET", "/api/reports/current")
    return body.get("report") if status == 200 and isinstance(body, dict) else None


def clear_fresh(base: str) -> None:
    """Undo every fresh report, so each check starts without one."""
    for _ in range(20):
        r = current(base)
        if not r:
            return
        _api(base, "DELETE", f"/api/reports/{r['id']}")


def _iso(now: str, minutes: float) -> str:
    t = datetime.fromisoformat(now.replace("Z", "+00:00")) + timedelta(minutes=minutes)
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- the page ------------------------------------------------------------------

STATE = """(() => {
  const hs = [...document.querySelectorAll('[data-report-host]')];
  if (hs.length !== 1) return {error: hs.length + ' elements with data-report-host (expected 1)'};
  const h = hs[0], r = h.getBoundingClientRect();
  const vis = (el) => !!el && el.isConnected && !el.closest('[hidden]')
    && el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})
    && el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0;
  const inert = (el) => !!el.closest('[inert]');
  const back = h.querySelector('[data-test="report-back"]');
  const front = [...h.querySelectorAll('[data-test]')].filter((el) => !back || !back.contains(el));
  const a = document.activeElement;
  const open = h.querySelectorAll('[data-test="report-open"]');
  const outside = [...document.querySelectorAll('[data-test^="report-"]')].filter((el) => !h.contains(el))
    .map((el) => el.dataset.test);
  return {id: h.id, rect: [r.x, r.y, r.width, r.height], back: !!back,
    backLive: !!back && vis(back) && !inert(back),
    frontLive: front.filter((el) => vis(el) && !inert(el)).map((el) => el.dataset.test),
    openLive: [...open].filter((el) => vis(el) && !inert(el)).length, openCount: open.length, outside,
    focusInBack: !!back && back.contains(a), focus: a ? (a.dataset.test || a.tagName.toLowerCase()) : null,
    scene: document.documentElement.getAttribute('data-scene'),
    sh: document.documentElement.scrollHeight, ih: document.documentElement.clientHeight};
})()"""

FIT = """(() => {
  const h = document.querySelector('[data-report-host]'), hr = h.getBoundingClientRect();
  const back = h.querySelector('[data-test="report-back"]');
  const vis = (el) => el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})
    && el.getBoundingClientRect().width > 0;
  const name = (el) => el.dataset.test + (el.dataset.kind ? '[' + el.dataset.kind + ']' : '')
    + (el.dataset.minutes ? '[' + el.dataset.minutes + ']' : '');
  const out = [];
  const items = [...back.querySelectorAll('[data-test]')].filter(vis);
  if (!items.length) return ['nothing visible on the back'];
  for (const el of items) {
    const r = el.getBoundingClientRect();
    if (r.left < hr.left - 1 || r.right > hr.right + 1 || r.top < hr.top - 1 || r.bottom > hr.bottom + 1)
      out.push(name(el) + ' sticks out of the tile: ' + [r.left, r.top, r.right, r.bottom].map(Math.round)
        + ' outside ' + [hr.left, hr.top, hr.right, hr.bottom].map(Math.round));
  }
  const buttons = items.filter((el) => ['report-kind', 'report-when', 'report-close', 'report-confirm']
    .includes(el.dataset.test));
  for (const el of buttons) {
    const r = el.getBoundingClientRect();
    const x = r.left + r.width / 2, y = r.top + r.height / 2;
    const top = document.elementFromPoint(x, y);
    if (y >= 0 && y <= innerHeight && !(top && (top === el || el.contains(top))))
      out.push(name(el) + ' is covered by ' + (top ? top.tagName.toLowerCase() + '.' + top.className : 'nothing'));
  }
  const kinds = items.filter((el) => el.dataset.test === 'report-kind');
  for (const el of kinds) {
    const r = el.getBoundingClientRect();
    if (r.width < %(min)d - 0.5 || r.height < %(min)d - 0.5)
      out.push(name(el) + ' is ' + Math.round(r.width) + 'x' + Math.round(r.height) + ' px (touch target %(min)dx%(min)d)');
  }
  for (let i = 0; i < buttons.length; i++) for (let j = i + 1; j < buttons.length; j++) {
    const a = buttons[i].getBoundingClientRect(), b = buttons[j].getBoundingClientRect();
    if (a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1)
      out.push(name(buttons[i]) + ' overlaps ' + name(buttons[j]));
  }
  return out;
})()""" % {"min": REPORT_MIN_BUTTON}


def state(pg) -> dict:
    """The host's live state (front/back parts, focus, size, scene) from the page."""
    return pg.js(STATE)


TURNING = """(() => { const h = document.querySelector('[data-report-host]');
  return !!h && document.getAnimations().some((a) => a.playState === 'running' && a.effect && a.effect.target
    && (h === a.effect.target || h.contains(a.effect.target))); })()"""


def settle_turn(pg, seconds: float = 2.0) -> list[str]:
    """Wait until the tile's turn (its animations and transitions) has ended."""
    end = time.monotonic() + seconds
    while pg.js(TURNING):
        if time.monotonic() > end:
            return [f"the tile still animates {seconds} s after the click"]
        pg.p.wait_idle(timeout=0.2, idle=0.05)
    pg.settle()
    return []


def open_back(pg) -> list[str]:
    """Click the ↻ button; the back must be live within 1.5 s (measured after the turn)."""
    problems = pg.click(selector='[data-report-host] [data-test="report-open"]')
    if problems:
        return problems
    return (wait(pg, lambda s: s.get("backLive") and not s.get("frontLive"), 1.5, "the back to show")
            or settle_turn(pg))


HIDE_FRONT = """(() => { const h = document.querySelector('[data-report-host]');
  const back = h.querySelector('[data-test="report-back"]');
  for (const c of h.children) if (c !== back && !c.contains(back)) c.style.visibility = 'hidden'; })()"""


def back_contrast(pg) -> list[str]:
    """WCAG AA on the open back. The front's texts are hidden first: a turned
    tile doesn't paint them, but the text probe would still measure them."""
    problems = open_back(pg)
    if problems:
        return problems
    pg.js(HIDE_FRONT)
    return contrast_problems(pg)


def wait(pg, cond, seconds, what) -> list[str]:
    """Wait for a state condition (at most seconds); the problem if it never holds."""
    end = time.monotonic() + seconds
    s = state(pg)
    while not cond(s) and time.monotonic() < end:
        pg.p.wait_idle(timeout=0.3, idle=0.1)
        s = state(pg)
    if cond(s):
        return []
    return [f"waited {seconds} s for {what}: back live {s.get('backLive')}, live front parts {s.get('frontLive')}, "
            f"focus {s.get('focus')}{' (' + s['error'] + ')' if 'error' in s else ''}"]


def closed_problems(s: dict) -> list[str]:
    """Problems if the host's back is not properly closed (hidden, front live)."""
    if "error" in s:
        return [s["error"]]
    out = []
    if not s["back"]:
        out.append("no [data-test=report-back] inside the host")
    if s["backLive"]:
        out.append("the back is live (shown and not inert) while closed")
    if not s["frontLive"]:
        out.append("no live front part while closed")
    if s["outside"]:
        out.append(f"report parts outside the host: {sorted(set(s['outside']))}")
    return out


def sel(hook: str, **data) -> str:
    """A CSS selector for a report element by data-test, plus optional data- attributes."""
    extra = "".join(f'[data-{k}="{v}"]' for k, v in data.items())
    return f'[data-report-host] [data-test="{hook}"]{extra}'


def visible(pg, hook) -> list[dict]:
    """The visible [data-test=hook] elements on the page."""
    return [e for e in pg.ui(hook) if e["visible"]]


def line_problems(pg, lang, report: dict, base_now: str) -> list[str]:
    """The front's line for this report, inside the host, with an undo button."""
    scene = kind_scene(report, report["observed_at"])
    key = "line-confirmed" if report.get("confirms") else "line"
    want = REPORT_TEXT[key][lang].format(scene=SCENE_LABEL[scene][LANG_I[lang]], time=pg.times([report["observed_at"]])[0])
    lines = pg.js("""[...document.querySelectorAll('[data-report-host] [data-test="report-line"]')]
        .filter((el) => el.checkVisibility({checkOpacity: true}) && !el.closest('[inert]'))
        .map((el) => el.textContent)""")
    if len(lines) != 1:
        return [f"{len(lines)} visible [data-test=report-line] on the host's front, expected 1 ({want!r})"]
    out = [] if has(lines[0], want) else [f"[data-test=report-line] shows {norm(lines[0])!r}, expected {want!r}"]
    undo = visible(pg, "report-undo")
    if len(undo) != 1 or norm(undo[0]["name"]) != REPORT_TEXT["undo"][lang]:
        out.append(f"report-undo: {[u['name'] for u in undo]}, expected one {REPORT_TEXT['undo'][lang]!r}")
    return out


def kind_scene(report: dict, at_iso: str) -> str:
    """The expected scene (day/night only matters for clear and partly cloudy; the
    report checks run at 10:50Z or 20:50Z in Berlin)."""
    day = 5 <= int(at_iso[11:13]) < 17
    kind, intensity = report["kind"], report.get("intensity")
    if kind in ("clear", "partly-cloudy"):
        return f"{kind}-{'day' if day else 'night'}"
    if kind == "rain" and intensity == "heavy":
        return "heavy-rain"
    return kind


# the closed host's report button (icon + word) lies over none of the host's texts
OPEN_CLEAR = """(() => {
  const out = [];
  for (const h of document.querySelectorAll('[data-report-host]')) {
    const b = h.querySelector('[data-test="report-open"]');
    if (!b || !b.checkVisibility()) continue;
    const br = b.getBoundingClientRect();
    const walk = document.createTreeWalker(h, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      const el = n.parentElement;
      if (!n.nodeValue.trim() || b.contains(n) || el.closest('[data-test="report-back"]')) continue;
      if (!el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) continue;
      const r = document.createRange(); r.selectNodeContents(n);
      for (const x of r.getClientRects()) {
        const ix = Math.min(br.right, x.right) - Math.max(br.left, x.left);
        const iy = Math.min(br.bottom, x.bottom) - Math.max(br.top, x.top);
        if (ix > 1 && iy > 1) {
          out.push(`at ${innerWidth}x${innerHeight}: report-open (${Math.round(br.left)},${Math.round(br.top)} ` +
            `${Math.round(br.width)}x${Math.round(br.height)}) lies over the text "${n.nodeValue.trim().slice(0, 40)}"`);
          break;
        }
      }
    }
  }
  return out;
})()"""


def open_label_problems(pg, opens, lang) -> list[str]:
    """A pencil (inline SVG) and a visible word, the word is the accessible name
    (WCAG 2.5.3), the touch target at least 44x44 px."""
    want = REPORT_TEXT["open"][lang]
    out = []
    for e in opens:
        if norm(e["text"]) != want:
            out.append(f"report-open shows the text {e['text']!r}, expected {want!r} next to the icon")
        if norm(e["name"]) != want:
            out.append(f"report-open is called {e['name']!r}, expected {want!r} (the visible text)")
        if e["rect"]["w"] < 44 or e["rect"]["h"] < 44:
            out.append(f"report-open is {e['rect']['w']:.0f}x{e['rect']['h']:.0f} px, expected at least 44x44")
    svgs = pg.js("""[...document.querySelectorAll('[data-report-host] [data-test="report-open"]')]
      .filter((e) => e.checkVisibility()).map((e) => e.querySelectorAll('svg').length)""")
    out += [f"report-open has {n} <svg>, expected 1 (the pencil)" for n in svgs if n != 1]
    return out


def picker_problems(pg, lang) -> list[str]:
    """The back's picker: the title, the kind buttons, the when chips, and the close."""
    i = LANG_I[lang]
    out = []
    title = visible(pg, "report-title")
    if len(title) != 1 or norm(title[0]["text"]) != REPORT_TEXT["title"][lang]:
        out.append(f"report-title: {[t['text'] for t in title]}, expected {REPORT_TEXT['title'][lang]!r}")
    kinds = visible(pg, "report-kind")
    got = [k["attrs"].get("data-kind") for k in kinds]
    if got != REPORT_KINDS:
        out.append(f"report-kind data-kind {got}, expected {REPORT_KINDS}")
    for k in kinds:
        kind = k["attrs"].get("data-kind")
        want = REPORT_KIND_LABEL.get(kind, ("?", "?"))[i]
        if norm(k["name"]) != want:
            out.append(f"report-kind[{kind}] is called {k['name']!r}, expected {want!r}")
    icons = pg.js("""[...document.querySelectorAll('[data-report-host] [data-test="report-kind"]')]
        .filter((b) => ![...b.querySelectorAll('svg')].some((s) => s.checkVisibility() && s.getBoundingClientRect().width >= 16))
        .map((b) => b.dataset.kind)""")
    if icons:
        out.append(f"report-kind without a visible picture (an <svg> of at least 16 px): {icons}")
    when = visible(pg, "report-when")
    got = [(w["attrs"].get("data-minutes"), w["attrs"].get("aria-pressed")) for w in when]
    want = [("0", "true"), ("15", "false"), ("30", "false")]
    if got != want:
        out.append(f"report-when (data-minutes, aria-pressed) {got}, expected {want}")
    for w in when:
        label = REPORT_WHEN.get(w["attrs"].get("data-minutes"), ("?", "?"))[i]
        if norm(w["name"]) != label:
            out.append(f"report-when[{w['attrs'].get('data-minutes')}] is called {w['name']!r}, expected {label!r}")
    close = visible(pg, "report-close")
    if len(close) != 1 or norm(close[0]["name"]) != REPORT_TEXT["close"][lang]:
        out.append(f"report-close: {[c['name'] for c in close]}, expected one {REPORT_TEXT['close'][lang]!r}")
    # a time chip toggles: 15 pressed, 0 not
    if not out:
        problems = pg.click(selector=sel("report-when", minutes="15"))
        got = [(w["attrs"].get("data-minutes"), w["attrs"].get("aria-pressed")) for w in visible(pg, "report-when")]
        if problems or got != [("0", "false"), ("15", "true"), ("30", "false")]:
            out.append(f"after a click on 15 min: {problems or got}")
    return out


def shows_problems(pg, lang, scene) -> list[str]:
    """The back's "shows" line, the aria-current kind, and the confirm button."""
    i = LANG_I[lang]
    out = []
    shows = visible(pg, "report-shows")
    label = SCENE_LABEL.get(scene, ("?", "?"))[i]
    want = REPORT_TEXT["shows"][lang].format(scene=label)
    if len(shows) != 1 or not has(shows[0]["text"], want):
        out.append(f"report-shows: {[s['text'] for s in shows]}, expected {want!r} (data-scene {scene!r})")
    kind = REPORT_SCENE_KIND.get(scene)
    current_kinds = [k["attrs"].get("data-kind") for k in visible(pg, "report-kind") if k["attrs"].get("aria-current") == "true"]
    if current_kinds != ([kind[0]] if kind else []):
        out.append(f"report-kind with aria-current=true: {current_kinds}, expected {[kind[0]] if kind else []}")
    confirm = visible(pg, "report-confirm")
    if kind and (len(confirm) != 1 or norm(confirm[0]["name"]) != REPORT_TEXT["confirm"][lang]):
        out.append(f"report-confirm: {[c['name'] for c in confirm]}, expected one {REPORT_TEXT['confirm'][lang]!r}")
    if not kind and confirm:
        out.append(f"report-confirm shown for scene {scene!r}, which no report kind names")
    return out
