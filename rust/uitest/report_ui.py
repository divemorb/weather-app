"""UI checks for the user reports (report steps W1-W3, 2026-10-07).

The tile with ``data-report-host`` (today Now) turns over: its ``report-open``
button shows the back (``report-back``) with the picker; a tap saves the
report (``POST /api/reports``) and turns the tile back, whose front then
shows ``report-line`` with ``report-undo``. The sky follows a fresh report
(``GET /api/reports/current``) and the "why" line names it; Details scores
the models against the reports (``user_reports`` of /api/model-accuracy).

Nothing here names ``#now``: the host is found by its attribute, and the
``report-glance`` UI scenario runs the same checks with the attribute moved
to the glance (a patched copy of app/static), so another tile can host the
picker after the user's acceptance test. Called from run.py (``ui`` is that
module: UIPage, contrast_problems, norm, has).
"""
from __future__ import annotations

import json
import re
import shutil
import time
import urllib.request
from datetime import datetime, timedelta, timezone

from expect import (MODEL_LABELS, REPORT_FIT, REPORT_INTENSITY, REPORT_KIND_LABEL, REPORT_KINDS,
                    REPORT_MIN_BUTTON, REPORT_SAVE_S, REPORT_SCENE_KIND, REPORT_SKY_CASES, REPORT_TEXT,
                    REPORT_WHEN, SCENE_LABEL)

LANG_I = {"en": 0, "de": 1}

# W1a: the flip and the picker; W1b: saving; W2: the sky; W3: Details.
FLIP = (["report-open", "report-closed", "report-flip", "report-picker", "report-shows", "report-close",
         "report-escape", "report-locked", "report-motion", "report-still", "report-buttons",
         "report-contrast-light", "report-contrast-dark", "report-open-clear"] + [f"report-fit-{v}" for v in REPORT_FIT])
SAVE = ["report-save", "report-undo", "report-intensity", "report-skip", "report-confirm", "report-error",
        "report-line-fresh"]
SKY = [f"sky-report-{c}" for c in REPORT_SKY_CASES] + ["sky-report-none", "sky-after-save"]
DETAILS = ["details-reports", "details-reports-fit"]
GLANCE_HOST = ["report-open", "report-closed", "report-flip", "report-fit-big-1280x800", "report-fit-phone-360",
               "report-open-clear", "report-save", "report-undo"]


def check_names(scenario: str, lang: str) -> list[str]:
    if scenario == "report":
        return ["console", "requests"] + FLIP + SAVE + SKY + DETAILS
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


def back_contrast(pg, ui) -> list[str]:
    """WCAG AA on the open back. The front's texts are hidden first: a turned
    tile doesn't paint them, but the text probe would still measure them."""
    problems = open_back(pg)
    if problems:
        return problems
    pg.js(HIDE_FRONT)
    return ui.contrast_problems(pg)


def wait(pg, cond, seconds, what) -> list[str]:
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
    extra = "".join(f'[data-{k}="{v}"]' for k, v in data.items())
    return f'[data-report-host] [data-test="{hook}"]{extra}'


def visible(pg, hook) -> list[dict]:
    return [e for e in pg.ui(hook) if e["visible"]]


def line_problems(pg, ui, lang, report: dict, base_now: str) -> list[str]:
    """The front's line for this report, inside the host, with an undo button."""
    scene = kind_scene(report, report["observed_at"])
    key = "line-confirmed" if report.get("confirms") else "line"
    want = REPORT_TEXT[key][lang].format(scene=SCENE_LABEL[scene][LANG_I[lang]], time=pg.times([report["observed_at"]])[0])
    lines = pg.js("""[...document.querySelectorAll('[data-report-host] [data-test="report-line"]')]
        .filter((el) => el.checkVisibility({checkOpacity: true}) && !el.closest('[inert]'))
        .map((el) => el.textContent)""")
    if len(lines) != 1:
        return [f"{len(lines)} visible [data-test=report-line] on the host's front, expected 1 ({want!r})"]
    out = [] if ui.has(lines[0], want) else [f"[data-test=report-line] shows {ui.norm(lines[0])!r}, expected {want!r}"]
    undo = visible(pg, "report-undo")
    if len(undo) != 1 or ui.norm(undo[0]["name"]) != REPORT_TEXT["undo"][lang]:
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


# --- the run --------------------------------------------------------------------

# P3: the closed host's report button (icon + word) lies over none of the host's texts
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


def open_label_problems(ui, pg, opens, lang) -> list[str]:
    """P3: a pencil (inline SVG) and a visible word, the word is the accessible name
    (WCAG 2.5.3), the touch target at least 44x44 px."""
    want = REPORT_TEXT["open"][lang]
    out = []
    for e in opens:
        if ui.norm(e["text"]) != want:
            out.append(f"report-open shows the text {e['text']!r}, expected {want!r} next to the icon")
        if ui.norm(e["name"]) != want:
            out.append(f"report-open is called {e['name']!r}, expected {want!r} (the visible text)")
        if e["rect"]["w"] < 44 or e["rect"]["h"] < 44:
            out.append(f"report-open is {e['rect']['w']:.0f}x{e['rect']['h']:.0f} px, expected at least 44x44")
    svgs = pg.js("""[...document.querySelectorAll('[data-report-host] [data-test="report-open"]')]
      .filter((e) => e.checkVisibility()).map((e) => e.querySelectorAll('svg').length)""")
    out += [f"report-open has {n} <svg>, expected 1 (the pencil)" for n in svgs if n != 1]
    return out


def run(ui, name, sc, browser, base, lang, names, add, done, shot):
    i = LANG_I[lang]
    now = sc["now"]
    page = lambda **kw: ui.UIPage(browser, base, now, lang, **kw)  # noqa: E731
    clear_fresh(base)

    # A: desktop (the big view): closed, open, the picker
    pg = page()
    s = state(pg)
    add("report-closed", closed_problems(s))
    opens = [e for e in pg.ui("report-open") if e["visible"]]
    add("report-open", ([] if s.get("openLive") == 1 and len(opens) == 1 else
                        [f"{len(opens)} visible [data-test=report-open] ({s.get('openCount')} in the host), expected 1"])
        + open_label_problems(ui, pg, opens, lang))
    before = s.get("rect")
    problems = open_back(pg)
    s = state(pg)
    if not problems:
        if not s["focusInBack"]:
            problems.append(f"the focus is on {s['focus']!r}, not inside the back")
        if before and any(abs(a - b) > 1 for a, b in zip(before[2:], s["rect"][2:])):
            problems.append(f"the tile changed its size: {before[2:]} -> {s['rect'][2:]}")
    add("report-flip", problems)
    if "report-picker" in names:
        add("report-picker", picker_problems(pg, ui, lang) if not problems else ["the back did not open"])
    if "report-shows" in names:
        add("report-shows", shows_problems(pg, ui, lang, s.get("scene")) if not problems else ["the back did not open"])
    if "report-buttons" in names:
        add("report-buttons", pg.js("__ui.controls()"))
    shot(pg, "report-back")
    # close with the button: the front again, the focus back on ↻, nothing saved
    if "report-close" in names:
        problems = pg.click(selector=sel("report-close"))
        problems += (wait(pg, lambda s: not s.get("backLive") and s.get("frontLive"), 1.5, "the front")
                     or settle_turn(pg))
        s = state(pg)
        if not problems and s["focus"] != "report-open":
            problems.append(f"the focus is on {s['focus']!r}, expected report-open")
        if current(base):
            problems.append("closing saved a report")
        add("report-close", problems)
    if "report-escape" in names:
        problems = open_back(pg)
        if not problems:
            pg.p.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Escape", "code": "Escape",
                                                 "windowsVirtualKeyCode": 27})
            pg.p.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Escape", "code": "Escape",
                                                 "windowsVirtualKeyCode": 27})
            problems = wait(pg, lambda s: not s.get("backLive") and s.get("frontLive"), 1.5, "Escape to close")
        add("report-escape", problems + (["Escape saved a report"] if current(base) else []))
    done(pg)

    for theme in ("light", "dark"):
        if f"report-contrast-{theme}" in names:
            pg = page(scheme=theme)
            add(f"report-contrast-{theme}", back_contrast(pg, ui))
            done(pg)

    # the back fits the host everywhere, the host keeps its size, the big view doesn't scroll
    clear = []
    for variant, (w, h, query) in REPORT_FIT.items():
        if f"report-fit-{variant}" not in names:
            continue
        pg = page(width=w, height=h, query=query)
        pg.js("document.querySelector('[data-report-host]').scrollIntoView({block: 'center'})")
        before = state(pg)
        if not query:
            clear += pg.js(OPEN_CLEAR)
        problems = open_back(pg)
        if not problems:
            after = state(pg)
            problems = pg.js(FIT)
            if any(abs(a - b) > 1 for a, b in zip(before["rect"][2:], after["rect"][2:])):
                problems.append(f"the tile changed its size: {before['rect'][2:]} -> {after['rect'][2:]}")
            if query == "" and w >= 1000 and after["sh"] > after["ih"] + 1:
                problems.append(f"the big view scrolls with the back open ({after['sh']} > {after['ih']} px)")
        add(f"report-fit-{variant}", problems)
        shot(pg, f"report-fit-{variant}", full=False)
        done(pg)
    if "report-open-clear" in names:
        add("report-open-clear", clear)

    if "report-locked" in names:
        pg = page(width=1280, height=800, query="?kiosk")
        n = len(visible(pg, "report-open"))
        add("report-locked", [f"{n} visible [data-test=report-open] on the locked wall display"] if n else [])
        done(pg)

    if "report-motion" in names:
        for check, reduced in (("report-motion", False), ("report-still", True)):
            pg = page(reduced=reduced)
            running = pg.js("""(() => { const h = document.querySelector('[data-report-host]');
                h.querySelector('[data-test="report-open"]').click();
                return document.getAnimations().filter((a) => a.playState === 'running'
                  && a.effect && a.effect.target && (h === a.effect.target || h.contains(a.effect.target)))
                  .map((a) => a.animationName || a.transitionProperty || 'animation'); })()""")
            if reduced:
                add(check, [f"the turn animates with prefers-reduced-motion: {running}"] if running else [])
            else:
                add(check, [] if running else ["no animation or transition runs in the tile when it turns"])
            done(pg)

    # B: saving (W1b)
    if "report-save" in names:
        run_save(ui, pg_factory=page, base=base, now=now, lang=lang, names=names, add=add, done=done, shot=shot)

    # C: the sky follows a fresh report (W2), with faked answers
    if "sky-report-none" in names:
        run_sky(ui, browser, base, now, lang, names, add, done)

    # D: Details (W3)
    if "details-reports" in names:
        pg = page(query="?detailed")
        pg.js("__ui.openDetails()")
        pg.settle()
        add("details-reports", details_problems(pg, ui, lang, base))
        shot(pg, "report-details")
        done(pg)
        pg = page(width=360, height=740, query="?detailed")
        pg.js("__ui.openDetails()")
        pg.settle()
        info = pg.js("__ui.page()")
        add("details-reports-fit", ([] if info["sw"] <= 361 else [f"page is {info['sw']} px wide at 360 px"])
            + [f"at 360 px: {p}" for p in pg.js('__ui.sticksOut("details")')])
        done(pg)
    clear_fresh(base)


def picker_problems(pg, ui, lang) -> list[str]:
    i = LANG_I[lang]
    out = []
    title = visible(pg, "report-title")
    if len(title) != 1 or ui.norm(title[0]["text"]) != REPORT_TEXT["title"][lang]:
        out.append(f"report-title: {[t['text'] for t in title]}, expected {REPORT_TEXT['title'][lang]!r}")
    kinds = visible(pg, "report-kind")
    got = [k["attrs"].get("data-kind") for k in kinds]
    if got != REPORT_KINDS:
        out.append(f"report-kind data-kind {got}, expected {REPORT_KINDS}")
    for k in kinds:
        kind = k["attrs"].get("data-kind")
        want = REPORT_KIND_LABEL.get(kind, ("?", "?"))[i]
        if ui.norm(k["name"]) != want:
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
        if ui.norm(w["name"]) != label:
            out.append(f"report-when[{w['attrs'].get('data-minutes')}] is called {w['name']!r}, expected {label!r}")
    close = visible(pg, "report-close")
    if len(close) != 1 or ui.norm(close[0]["name"]) != REPORT_TEXT["close"][lang]:
        out.append(f"report-close: {[c['name'] for c in close]}, expected one {REPORT_TEXT['close'][lang]!r}")
    # a time chip toggles: 15 pressed, 0 not
    if not out:
        problems = pg.click(selector=sel("report-when", minutes="15"))
        got = [(w["attrs"].get("data-minutes"), w["attrs"].get("aria-pressed")) for w in visible(pg, "report-when")]
        if problems or got != [("0", "false"), ("15", "true"), ("30", "false")]:
            out.append(f"after a click on 15 min: {problems or got}")
    return out


def shows_problems(pg, ui, lang, scene) -> list[str]:
    i = LANG_I[lang]
    out = []
    shows = visible(pg, "report-shows")
    label = SCENE_LABEL.get(scene, ("?", "?"))[i]
    want = REPORT_TEXT["shows"][lang].format(scene=label)
    if len(shows) != 1 or not ui.has(shows[0]["text"], want):
        out.append(f"report-shows: {[s['text'] for s in shows]}, expected {want!r} (data-scene {scene!r})")
    kind = REPORT_SCENE_KIND.get(scene)
    current_kinds = [k["attrs"].get("data-kind") for k in visible(pg, "report-kind") if k["attrs"].get("aria-current") == "true"]
    if current_kinds != ([kind[0]] if kind else []):
        out.append(f"report-kind with aria-current=true: {current_kinds}, expected {[kind[0]] if kind else []}")
    confirm = visible(pg, "report-confirm")
    if kind and (len(confirm) != 1 or ui.norm(confirm[0]["name"]) != REPORT_TEXT["confirm"][lang]):
        out.append(f"report-confirm: {[c['name'] for c in confirm]}, expected one {REPORT_TEXT['confirm'][lang]!r}")
    if not kind and confirm:
        out.append(f"report-confirm shown for scene {scene!r}, which no report kind names")
    return out


def run_save(ui, pg_factory, base, now, lang, names, add, done, shot):
    def saved_and_back(pg, want: dict) -> list[str]:
        end = time.monotonic() + REPORT_SAVE_S
        got = None
        while time.monotonic() < end:
            got = current(base)
            s = state(pg)
            if got and not s.get("backLive") and s.get("frontLive"):
                break
            pg.p.wait_idle(timeout=0.3, idle=0.1)
        out = []
        if not got:
            return [f"nothing saved within {REPORT_SAVE_S} s (GET /api/reports/current is null)"]
        for k, v in want.items():
            if got.get(k) != v:
                out.append(f"saved {k}={got.get(k)!r}, expected {v!r} (report {got})")
        s = state(pg)
        if s.get("backLive") or not s.get("frontLive"):
            out.append(f"the tile did not turn back within {REPORT_SAVE_S} s")
        return out

    # fog, 15 min ago
    clear_fresh(base)
    pg = pg_factory()
    problems = open_back(pg)
    problems = problems or pg.click(selector=sel("report-when", minutes="15"))
    problems = problems or pg.click(selector=sel("report-kind", kind="fog"))
    problems = problems or saved_and_back(pg, {"kind": "fog", "intensity": None, "confirms": False,
                                               "observed_at": _iso(now, -15)})
    rep = current(base)
    if not problems and rep:
        problems = line_problems(pg, ui, lang, rep, now)
    add("report-save", problems)
    shot(pg, "report-saved")
    if "sky-after-save" in names:
        problems = []
        if rep:
            scene = kind_scene(rep, rep["observed_at"])
            got = pg.js("document.documentElement.getAttribute('data-scene')")
            if got != scene:
                problems.append(f"data-scene {got!r} after saving {rep['kind']}, expected {scene!r}")
            want = REPORT_TEXT["sky"][lang].format(scene=SCENE_LABEL[scene][LANG_I[lang]], time=pg.times([rep["observed_at"]])[0])
            reason = visible(pg, "sky-reason")
            if len(reason) != 1 or ui.norm(reason[0]["text"]) != want:
                problems.append(f"sky-reason {[r['text'] for r in reason]}, expected {want!r}")
        else:
            problems.append("nothing saved (see report-save)")
        add("sky-after-save", problems)
    # undo
    problems = [] if rep else ["nothing saved (see report-save)"]
    if rep:
        problems = pg.click(selector=sel("report-undo"))
        end = time.monotonic() + REPORT_SAVE_S
        while current(base) and time.monotonic() < end:
            pg.p.wait_idle(timeout=0.3, idle=0.1)
        if current(base):
            problems.append("the report is still there after undo")
        n = pg.js("[...document.querySelectorAll('[data-report-host] [data-test=\"report-line\"]')]"
                  ".filter((el) => el.checkVisibility()).length")
        if n:
            problems.append("report-line still visible after undo")
    add("report-undo", problems)
    done(pg)

    # rain, heavy
    for check, button, want in (("report-intensity", ("report-intensity", {"intensity": "heavy"}), "heavy"),
                                ("report-skip", ("report-intensity-skip", {}), None)):
        clear_fresh(base)
        pg = pg_factory()
        problems = open_back(pg) or pg.click(selector=sel("report-kind", kind="rain"))
        if not problems:
            choices = visible(pg, "report-intensity")
            got = [(c["attrs"].get("data-intensity"), ui.norm(c["name"])) for c in choices]
            exp = [(k, v[LANG_I[lang]]) for k, v in REPORT_INTENSITY.items()]
            if got != exp:
                problems.append(f"report-intensity (data-intensity, name) {got}, expected {exp}")
            skip = visible(pg, "report-intensity-skip")
            if len(skip) != 1 or ui.norm(skip[0]["name"]) != REPORT_TEXT["skip"][lang]:
                problems.append(f"report-intensity-skip: {[x['name'] for x in skip]}, expected {REPORT_TEXT['skip'][lang]!r}")
            if current(base):
                problems.append("rain was saved before its intensity was chosen")
            problems += pg.js(FIT)
        if not problems:
            problems = pg.click(selector=sel(button[0], **button[1]))
            problems = problems or saved_and_back(pg, {"kind": "rain", "intensity": want, "confirms": False,
                                                       "observed_at": now})
            rep = current(base)
            if not problems and rep:
                problems = line_problems(pg, ui, lang, rep, now)
        add(check, problems)
        done(pg)

    # "That's right": what the page shows, confirmed
    clear_fresh(base)
    pg = pg_factory()
    scene = state(pg).get("scene")
    want = REPORT_SCENE_KIND.get(scene)
    problems = [] if want else [f"the page shows {scene!r}, which no report kind names (the check needs one)"]
    problems = problems or open_back(pg) or pg.click(selector=sel("report-confirm"))
    if not problems:
        problems = saved_and_back(pg, {"kind": want[0], "intensity": want[1], "confirms": True, "observed_at": now})
        rep = current(base)
        if not problems and rep:
            problems = line_problems(pg, ui, lang, rep, now)
    add("report-confirm", problems)
    done(pg)
    clear_fresh(base)

    # a failing save: the message, the back stays, nothing on the front
    pg = pg_factory(fakes={"/api/reports": [(500, json.dumps({"detail": "boom"}))] * 4})
    problems = open_back(pg) or pg.click(selector=sel("report-kind", kind="snow"))
    if not problems:
        pg.p.wait_idle(timeout=2, idle=0.3)
        err = visible(pg, "report-error")
        if len(err) != 1 or ui.norm(err[0]["text"]) != REPORT_TEXT["failed"][lang]:
            problems.append(f"report-error: {[e['text'] for e in err]}, expected {REPORT_TEXT['failed'][lang]!r}")
        if not state(pg).get("backLive"):
            problems.append("the back closed although nothing was saved")
        if visible(pg, "report-line"):
            problems.append("report-line shown although nothing was saved")
    add("report-error", problems)
    pg.close()  # its console has the faked 500 on purpose

    # a fresh report from earlier (another device): the front shows it on load
    rep = {"id": 77, "kind": "snow", "intensity": None, "confirms": False, "observed_at": _iso(now, -10)}
    pg = pg_factory(fakes={"/api/reports/current": [(200, json.dumps({"report": rep}))] * 8})
    add("report-line-fresh", line_problems(pg, ui, lang, rep, now))
    done(pg)


def run_sky(ui, browser, base, now, lang, names, add, done):
    i = LANG_I[lang]
    for case, (fields, clock, scene) in REPORT_SKY_CASES.items():
        if f"sky-report-{case}" not in names:
            continue
        at = clock or now
        rep = {"id": 90, "intensity": None, "confirms": False, **fields, "observed_at": _iso(at, -5)}
        pg = ui.UIPage(browser, base, at, lang,
                       fakes={"/api/reports/current": [(200, json.dumps({"report": rep}))] * 8})
        problems = []
        got = pg.js("document.documentElement.getAttribute('data-scene')")
        if got != scene:
            problems.append(f"data-scene {got!r} with a fresh {fields} report, expected {scene!r}")
        key = "sky-confirmed" if rep["confirms"] else "sky"
        want = REPORT_TEXT[key][lang].format(scene=SCENE_LABEL[scene][i], time=pg.times([rep["observed_at"]])[0])
        reason = visible(pg, "sky-reason")
        if len(reason) != 1 or ui.norm(reason[0]["text"]) != want:
            problems.append(f"sky-reason {[r['text'] for r in reason]}, expected {want!r}")
        add(f"sky-report-{case}", problems)
        done(pg)
    # no fresh report: the sky as before (the radar here)
    pg = ui.UIPage(browser, base, now, lang, fakes={"/api/reports/current": [(200, '{"report": null}')] * 8})
    reason = visible(pg, "sky-reason")
    text = reason[0]["text"] if reason else ""
    mine = "by you" if lang == "en" else "von dir"
    add("sky-report-none", [f"sky-reason names a report without one: {text!r}"] if mine in text else
        ([] if reason else ["no sky-reason shown"]))
    done(pg)


def details_problems(pg, ui, lang, base) -> list[str]:
    i = LANG_I[lang]
    status, body = _api(base, "GET", "/api/model-accuracy")
    ur = (body or {}).get("user_reports") if status == 200 else None
    if not isinstance(ur, dict):
        return [f"/api/model-accuracy has no user_reports (status {status})"]
    out = []
    sec = visible(pg, "accuracy-reports")
    if len(sec) != 1:
        return [f"{len(sec)} visible [data-test=accuracy-reports], expected 1"]
    if not ui.has(sec[0]["text"], REPORT_TEXT["acc-title"][lang]):
        out.append(f"accuracy-reports lacks its title {REPORT_TEXT['acc-title'][lang]!r}")
    inside = pg.js("(() => { const d = document.querySelector('[data-test=\"details\"]'); "
                   "const s = document.querySelector('[data-test=\"accuracy-reports\"]'); return !!d && !!s && d.contains(s); })()")
    if not inside:
        out.append("accuracy-reports is not inside the Details card")
    if not ur["models"]:
        none = visible(pg, "accuracy-reports-none")
        if len(none) != 1 or ui.norm(none[0]["text"]) != REPORT_TEXT["acc-none"][lang]:
            out.append(f"accuracy-reports-none: {[n['text'] for n in none]}, expected {REPORT_TEXT['acc-none'][lang]!r}")
        return out
    summary = visible(pg, "accuracy-reports-summary")
    want = REPORT_TEXT["acc-summary"][lang].format(hours=ur["hours"], confirmed=ur["confirmed_hours"])
    if len(summary) != 1 or ui.norm(summary[0]["text"]) != want:
        out.append(f"accuracy-reports-summary: {[s['text'] for s in summary]}, expected {want!r}")
    note = visible(pg, "accuracy-reports-note")
    if len(note) != 1 or ui.norm(note[0]["text"]) != ui.norm(REPORT_TEXT["acc-note"][lang]):
        out.append(f"accuracy-reports-note: {[n['text'][:60] for n in note]}, expected the fixed note")
    order = sorted(ur["models"], key=lambda m: -ur["models"][m]["event_accuracy"])  # stable: ties keep the API order
    rows = visible(pg, "accuracy-reports-row")
    got = [r["attrs"].get("data-model") for r in rows]
    if got != order:
        return out + [f"accuracy-reports-row data-model order {got}, expected {order} (best hit rate first)"]
    locale = "en-US" if lang == "en" else "de-DE"
    for r, model in zip(rows, order):
        m = ur["models"][model]
        pct = pg.js(f"new Intl.NumberFormat({locale!r}, {{style: 'percent', maximumFractionDigits: 0}})"
                    f".format({m['event_accuracy']})")
        cells = pg.js(f"[...document.querySelectorAll('[data-test=\"accuracy-reports-row\"][data-model=\"{model}\"] td')]"
                      ".map((td) => td.textContent.trim())")
        want = [MODEL_LABELS[model], str(m["n_samples"]), str(m["hits"]), str(m["misses"]), str(m["false_alarms"]), pct]
        if [ui.norm(c) for c in cells] != [ui.norm(w) for w in want]:
            out.append(f"row {model}: cells {cells}, expected {want}")
    return out


def none_problems(pg, ui, lang) -> list[str]:
    """Details without any report (the accuracy scenario): the none line, no rows."""
    out = []
    none = visible(pg, "accuracy-reports-none")
    if len(none) != 1 or ui.norm(none[0]["text"]) != REPORT_TEXT["acc-none"][lang]:
        out.append(f"accuracy-reports-none: {[n['text'] for n in none]}, expected {REPORT_TEXT['acc-none'][lang]!r}")
    if visible(pg, "accuracy-reports-row"):
        out.append("accuracy-reports-row shown without reports")
    return out
