"""The sky: faked /api/now icon and radar per scene, the sky layer, the motion,
the glass effect and the "why" line."""

from __future__ import annotations

import json
import time
import urllib.request

from expect import (CONTRAST_VIEWS, GLASS_DELTA, GLASS_MIN_RATIO, GLASS_SCENES, GLASS_GAP_S,
                    GLASS_VIEW, MOTION_GAP_S, MOTION_MIN, REASON_CASES, REASON_STATION,
                    REASON_TEXT, SCENE_CASES, SCENE_LABEL, SCENE_SOURCE, SCENES)
from page import Run, UIPage, expect_hidden, expect_text
from page_checks import contrast_problems

# --- the sky: faked /api/now icon and radar per scene ------------------------------------

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
    """The scene the page is showing (html[data-scene]), or None if unset."""
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


def run_sky(run: Run):
    """The sky's checks; the work of a check not in `names` (--only) is skipped."""
    now_body = _get_json(run.base + "/api/now")
    radar_body = _get_json(run.base + "/api/radar/next-hour")
    for case, (icon, radar, want) in SCENE_CASES.items():
        if f"scene-{case}" not in run.names and not (case == "cloudy" and "sky-layer" in run.names):
            continue
        pg = run.page(fakes=scene_fakes(case, now_body, radar_body))
        got = scene_of(pg)
        run.add(f"scene-{case}", [] if got == want else
                [f"<html data-scene={got!r}> with icon {icon!r} and radar {radar!r}, expected {want!r}"])
        if case == "cloudy":
            run.add("sky-layer", sky_layer_problems(pg))
        run.done(pg)
    for scene in SCENES:
        fakes = scene_fakes(SCENE_SOURCE[scene], now_body, radar_body)
        if scene != "none" and f"motion-{scene}" in run.names:
            pg = run.page(fakes=fakes)
            run.add(f"motion-{scene}", motion_problems(pg, scene, moving=True))
            run.done(pg)
        if f"still-{scene}" in run.names:
            pg = run.page(reduced=True, fakes=fakes)
            run.add(f"still-{scene}", motion_problems(pg, scene, moving=False))
            run.done(pg)
        if scene in GLASS_SCENES and f"glass-{scene}" in run.names:
            run.add(f"glass-{scene}", [p for theme in ("light", "dark")
                                       for p in glass_problems(run, scene, theme, fakes)])
        for theme in ("light", "dark"):
            if f"contrast-{scene}-{theme}" not in run.names:
                continue
            problems = []
            for w, h, query in CONTRAST_VIEWS:
                view = f"{w}x{h}{' ' + query if query else ''}"
                pg = run.page(width=w, height=h, scheme=theme, query=query, fakes=fakes)
                got = scene_of(pg)
                if got != scene:
                    problems.append(f"{view}: data-scene={got!r}, expected {scene!r}")
                problems += [f"{view}: {p}" for p in contrast_problems(pg)]
                if w >= 1280:  # frames for the review (the sleep is only there so
                    # consecutive --shots frames differ; without --shots it is pure waste)
                    for i in range(3):
                        run.shot(pg, f"scene-{scene}-{theme}-{view.replace(' ', '-')}-{i}", full=False)
                        if run.args.shots:
                            time.sleep(0.4)
                run.done(pg)
            run.add(f"contrast-{scene}-{theme}", problems)


def glass_problems(run: Run, scene: str, theme: str, fakes: dict) -> list[str]:
    """The default view at GLASS_VIEW, text made transparent: the moving sky changes
    the pixels inside the tiles at least GLASS_MIN_RATIO as much as outside them.
    The pair is seeked, not waited for: all animations paused, first frame at
    GLASS_BASE_MS, the second GLASS_GAP_S later."""
    w, h = GLASS_VIEW
    GLASS_BASE_MS = 3000
    pg = run.page(width=w, height=h, scheme=theme, fakes=fakes)
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
        # the two frames GLASS_GAP_S apart, seeked instead of waited for (the sky
        # is pure CSS keyframes; seeking leaves the animations paused, fine: the
        # page is closed in `finally`)
        pg.js(f"__ui.seekTime({GLASS_BASE_MS:.0f})")
        pg.frame()
        a = pg.shot_b64()
        pg.js(f"__ui.seekTime({GLASS_BASE_MS + GLASS_GAP_S * 1000:.0f})")
        pg.frame()
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
    """The "why" line for a REASON_CASES entry in a language; None when no line is shown."""
    src, form, _ = REASON_CASES[case]
    if form is None:
        return None
    icon, _, scene = SCENE_CASES[src]
    i = 0 if lang == "en" else 1
    name, km = REASON_STATION
    return REASON_TEXT[form][lang].format(scene=SCENE_LABEL[scene][i], name=name, km=km[lang],
                                          station=SCENE_LABEL[icon][i] if icon in SCENE_LABEL else "")


def run_reasons(run: Run):
    """[data-test=sky-reason]: what the sky shows and which source decided it (REASON_CASES)."""
    now_body = _get_json(run.base + "/api/now")
    radar_body = _get_json(run.base + "/api/radar/next-hour")
    for case, (src, form, listed) in REASON_CASES.items():
        pg = run.page(fakes=scene_fakes(src, now_body, radar_body, station=listed))
        want = reason_text(case, run.lang)
        problems = expect_hidden(pg, "sky-reason") if want is None else expect_text(pg, "sky-reason", want)
        got = scene_of(pg)
        if got != SCENE_CASES[src][2]:
            problems.append(f"data-scene={got!r}, expected {SCENE_CASES[src][2]!r}")
        run.add(f"reason-{case}", problems)
        pg.close()
