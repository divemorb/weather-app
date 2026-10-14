"""One scenario: starting the app, running its pages per language, and the
checks shared by the content scenarios (live, rain, errors, accuracy)."""

from __future__ import annotations

import importlib.util
import pathlib
import socket
import sys
import tempfile
import time
import types

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "contract"))  # the contract suite (fakeup, scenarios, ...)

from expect import FIXED, KIOSK_SIZES, LAYOUT_COLUMNS, NOW_STATION, SCENARIO  # noqa: E402
import report_run  # noqa: E402
import report_ui  # noqa: E402
from fakeup import FakeUpstream  # noqa: E402
from names import BACKEND, SCENARIO_LANGS, check_names  # noqa: E402
from page import UIPage, expect_hidden, expect_text, expect_tokens, visible_one  # noqa: E402
from page_checks import (check_chart, check_common_a, check_details, check_glance, check_kiosk,  # noqa: E402
                         check_now, check_radar, contrast_problems, theme_icon_problems,
                         theme_problems)
from big import kiosk_chart_problems, kiosk_fill_problems, kiosk_room_problems, run_big  # noqa: E402
from flows import refresh_config_retry, refresh_render_error, run_wizard, theme_toggle  # noqa: E402
from sky import run_reasons, run_sky  # noqa: E402
from views import now_fallback_problems, run_views  # noqa: E402

STATIC = HERE.parent.parent / "app" / "static"  # the app's static files (the default static dir)
PORT_BASE = 20000  # worker k may use the app ports 20000 + 100*k .. +100*k + 99
PORT_SPAN = 100

# the contract suite's run.py, loaded by path (this file is not the only run.py):
# it provides the scenario table (SCENARIOS) and the app helpers (start_backend,
# free_port, seed_db, make_config, ...); every other module uses it through here
_spec = importlib.util.spec_from_file_location("contract_run", HERE.parent / "contract" / "run.py")
contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(contract)
SCENARIOS = contract.SCENARIOS

# --- one scenario ---------------------------------------------------------------

class Results:
    def __init__(self):
        self.problems: dict[str, list[str]] = {}

    def add(self, name, problems):
        self.problems.setdefault(name, []).extend(problems)


def _free_in_range(base: int) -> int | None:
    """The first free port in ``base .. base + PORT_SPAN - 1`` (a socket
    bind test, as in ``contract.free_port``), or None if the range is full."""
    for port in range(base, base + PORT_SPAN):
        try:
            with socket.socket() as s:
                s.bind(("127.0.0.1", port))
            return port
        except OSError:
            continue
    return None


def start_app(sc: dict, args, tmp: pathlib.Path, static: pathlib.Path | None = None):
    """Start the app on a free port. In the main process the port comes from
    free_port() (nothing else is running); in a worker (T3) it is the first
    free port in the worker's fixed range 20000 + 100*k .. +100*k + 99, found
    by probing the range with a socket bind (the app exits fast when its port
    is busy, so a busy port would look like a crash); two workers must never
    pick the same port (their ranges are disjoint), and the rest of the range
    is only tried if the probed port turns out busy anyway."""
    fake = FakeUpstream(sc["routes"])
    db = tmp / "weather.db"
    if sc.get("seed"):
        contract.seed_db(db, sc["seed"], sc["now"])
    env = {"WEATHER_CONFIG": str(contract.make_config(tmp, fake.base)), "DATABASE_PATH": str(db),
           "WETTER_FAKE_NOW": sc["now"], **sc["env"]}
    if static is not None:
        env["STATIC_DIR"] = str(static)
    port, proc, error = None, None, None
    if getattr(args, "port_base", None) is None:
        port = contract.free_port()
        ns = types.SimpleNamespace(backend="rust", binary=args.binary, log=args.log)
        proc = contract.start_backend(ns, port, env)
        error = contract.wait_ready(port, proc)
    else:
        # the probed port first (the socket bind just found it free); the rest
        # of the range only as a fallback in case it turns out busy anyway
        probed = _free_in_range(args.port_base)
        ports = ([probed] if probed is not None else []) + [
            p for p in range(args.port_base, args.port_base + PORT_SPAN) if p != probed]
        for p in ports:
            ns = types.SimpleNamespace(backend="rust", binary=args.binary, log=args.log)
            proc = contract.start_backend(ns, p, env)
            error = contract.wait_ready(p, proc, timeout=10)
            if not error:
                port = p
                break
            contract.stop_backend(proc)
            proc = None
            if "not ready" in error:  # the port is busy: try the next one
                error = None
            else:  # the app crashed: retrying another port won't help
                break
        if port is None and proc is None and error is None:
            error = f"no free app port in {args.port_base}..{args.port_base + PORT_SPAN - 1}"
    return fake, proc, port, error


def run_scenario(name: str, browsers: dict, args, res: Results, checks: list[str] | None = None):
    """One scenario. ``checks`` (T3, the per-scene sky split): the check names
    this job runs (the rest of the scenario's checks are left to other jobs);
    None: all of the scenario's checks, as before."""
    sc = next(s for s in SCENARIOS if s["name"] == BACKEND.get(name, name))
    base_names = {lang: (checks if checks is not None else check_names(name, lang))
                  for lang in SCENARIO_LANGS.get(name, ["en", "de"])}
    langs = [lang for lang in SCENARIO_LANGS.get(name, ["en", "de"])
             if lang in browsers and any(args.selected(f"{name}/{lang}/{c}") for c in base_names[lang])]
    if not langs:
        return
    with tempfile.TemporaryDirectory(prefix="uitest-") as tmp:
        static = args.static
        if name == "report-glance":  # the same page with the report picker on the glance
            static = pathlib.Path(tmp) / "static"
            report_ui.static_copy(args.static or STATIC, static)
        fake, proc, port, error = start_app(sc, args, pathlib.Path(tmp), static)
        try:
            if error:
                for lang in langs:
                    for c in base_names[lang]:
                        res.add(f"{name}/{lang}/{c}", [f"app did not start: {error}"])
                return
            base = f"http://127.0.0.1:{port}"
            for lang in langs:
                prefix = f"{name}/{lang}/"
                names = [c for c in base_names[lang] if args.selected(prefix + c)]

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
    elif name == "fallback":
        pg = UIPage(browser, base, sc["now"], lang)
        add("now-station", expect_tokens(pg, "now-station", NOW_STATION[lang]))
        add("now-fallback", now_fallback_problems(pg))
        shot(pg, "desktop-light")
        done(pg)
    elif name == "sky":
        run_sky(browser, base, sc, lang, names, add, done, shot, args)
    elif name in ("report", "report-glance"):
        report_run.run(name, sc, browser, base, lang, names, add, done, shot)
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
                add("now-station", expect_tokens(pg, "now-station", NOW_STATION[lang]))
                add("now-fallback", [f"{n} visible [data-test=now-fallback]: no value fell back here"
                                     for n in [sum(e["visible"] for e in pg.ui("now-fallback"))] if n])
            else:
                add("now-unavailable", expect_text(pg, "now-unavailable", FIXED["now.unavailable"][lang])
                    + expect_hidden(pg, "now-temp"))
                add("now-station", expect_hidden(pg, "now-station"))
            check_chart(pg, exp, add)
        shot(pg, "desktop-light")
        done(pg)
        # A2: the details page (?detailed), light
        pg = UIPage(browser, base, sc["now"], lang, query="?detailed")
        check_details(pg, name, exp, names, add)
        if "details-reports-none" in names:
            add("details-reports-none", report_run.none_problems(pg, lang))
        add("details-contrast", [f"light: {p}" for p in contrast_problems(pg)])
        shot(pg, "desktop-details")
        done(pg)
        pg = UIPage(browser, base, sc["now"], lang, scheme="dark", query="?detailed")
        pg.js("__ui.openDetails()")
        pg.settle()
        add("details-contrast", [f"dark: {p}" for p in contrast_problems(pg)])
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
    if name in ("live", "rain", "errors", "unconfigured", "accuracy"):
        # C: phone, 360 px: the big view, then the details page (opened)
        for query in ("", "?detailed"):
            pg = UIPage(browser, base, sc["now"], lang, width=360, height=740, query=query)
            pg.js("__ui.openDetails()")
            pg.settle()
            info = pg.js("__ui.page()")
            where = "the details page" if query else "the big view"
            add("overflow-360", [] if info["sw"] <= 361 and info["iw"] <= 361 else
                [f"{where}: page is {info['sw']} px wide at 360 px (horizontal scrolling): {pg.js('__ui.overflowing()')}"])
            if query:
                add("details-fit", [f"at 360 px: {p}" for p in pg.js('__ui.sticksOut("details")')])
            shot(pg, f"phone-360{'-details' if query else ''}")
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
            if f"kiosk-chart-{size[0]}x{size[1]}" in names:
                add(f"kiosk-chart-{size[0]}x{size[1]}", kiosk_chart_problems(pg, size))
            add(f"kiosk-fill-{size[0]}x{size[1]}", kiosk_fill_problems(pg, exp, size))
            add(f"kiosk-room-{size[0]}x{size[1]}", kiosk_room_problems(pg, size))
            shot(pg, f"kiosk-{size[0]}x{size[1]}", full=False)
            done(pg)
    if "theme-toggle" in names:
        add("theme-toggle", theme_toggle(browser, base, sc, lang, done))
    if any(n.startswith("reason-") for n in names):
        run_reasons(browser, base, sc, lang, add)
    if "view-default" in names:
        run_views(browser, base, sc, lang, add)
    if "big-labels" in names:
        run_big(browser, base, sc, lang, names, add)
    for w in LAYOUT_COLUMNS:
        if f"layout-{w}" in names:
            pg = UIPage(browser, base, sc["now"], lang, width=w, height=740 if w < 600 else 900)
            add(f"layout-{w}", layout_problems(pg, w))
            shot(pg, f"layout-{w}")
            done(pg)
    if "refresh-render-error" in names:
        add("refresh-render-error", refresh_render_error(browser, base, sc, lang))
    if "refresh-config-retry" in names:
        add("refresh-config-retry", refresh_config_retry(browser, base, sc, lang))
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


def layout_problems(pg: UIPage, w: int) -> list[str]:
    """The big view's tiles at a page width (P2: the detailed view is the details page, so
    the tile grid is the big view's): glance, Now and the chart visible, the glance first
    (top left), no tile overlapping another, no horizontal scrolling."""
    t = pg.js("__ui.tiles()")
    if not t:
        return ["no main#dashboard"]
    problems = []
    tiles = t["list"]
    missing = {"glance", "now", "chart-card"} - {x["id"] for x in tiles}
    if missing:
        problems.append(f"{sorted(missing)} not visible in the big view at {w} px")
    by_id = {x["id"]: x for x in tiles}
    if not tiles or tiles[0]["id"] != "glance":
        problems.append(f"the first tile is {tiles[0]['id'] if tiles else None!r}, expected #glance")
    g = by_id.get("glance")
    if g:
        if any(o["y"] < g["y"] - 1 for o in tiles if o is not g):
            problems.append("a tile starts above #glance: the glance comes first")
        if g["x"] > t["x"] + 1:
            problems.append(f"#glance starts at x={g['x']:.0f}, not at the left edge of the tiles ({t['x']:.0f})")
    if "details" in by_id:
        problems.append("#details is visible in the big view")
    for i, a in enumerate(tiles):
        for b in tiles[i + 1:]:
            ox = min(a["right"], b["right"]) - max(a["x"], b["x"])
            oy = min(a["bottom"], b["bottom"]) - max(a["y"], b["y"])
            if ox > 1 and oy > 1:
                problems.append(f"#{a['id']} and #{b['id']} overlap ({ox:.0f}x{oy:.0f} px)")
    info = pg.js("__ui.page()")
    if info["sw"] > w + 1:
        problems.append(f"page is {info['sw']} px wide at {w} px: {pg.js('__ui.overflowing()')}")
    return problems
