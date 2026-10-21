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
from page import Run, UIPage, expect_hidden, expect_text, expect_tokens, visible_one  # noqa: E402
from page_checks import (check_chart, check_common_a, check_details, check_glance, check_kiosk,  # noqa: E402
                         check_now, check_radar, contrast_problems, page_unconfigured,
                         theme_icon_problems, theme_problems)
from big import kiosk_chart_problems, kiosk_fill_problems, kiosk_room_problems, run_big  # noqa: E402
from chart import chart_single_point  # noqa: E402
from clock import dst_chart_x_labels, dst_radar_labels  # noqa: E402
from markup import markup_api  # noqa: E402
from turn import kiosk_turn  # noqa: E402
from responsive import run_responsive  # noqa: E402
from edges import now_texts_problems, radar_unavailable_text_problems, setup_texts_problems  # noqa: E402
from flows import refresh_config_retry, refresh_render_error, run_wizard, theme_toggle  # noqa: E402
from outdated import refresh_keeps_old  # noqa: E402
from reload import reload_fires  # noqa: E402
from sky import run_reasons, run_sky  # noqa: E402
from views import page_fallback, run_views  # noqa: E402

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
    """The run's check results: check name -> its problem lines (none: pass)."""

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
    free_port() (nothing else is running); in a worker it is the first free
    port in the worker's fixed range 20000 + 100*k .. +100*k + 99, found
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
    """One scenario. ``checks``: the check names this job runs (the rest of
    the scenario's checks are left to other jobs); None: all of them."""
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
                    run_pages(Run(name, sc, browsers[lang], base, lang, names, add, args))
                except Exception as exc:  # noqa: BLE001 - report it, go on with the next language
                    add("console", [f"harness error: {exc!r}"])
                    for c in names:
                        if prefix + c not in res.problems:
                            add(c, [f"not checked: the page run stopped early ({exc!r})"])
        finally:
            contract.stop_backend(proc)
            fake.stop()



def run_pages(run: Run):
    """The scenario's page function, then the checks the scenarios share
    (content, the phone at 360 px, the kiosk and the common ones)."""
    if not responsive_only(run):
        PAGES[run.name](run)
        page_content(run)
        page_phone_360(run)
        if run.name == "unconfigured":
            page_unconfigured_dark(run)
    page_kiosk_and_common(run)


def responsive_only(run: Run) -> bool:
    """A job that runs only responsive sweeps (workers.build_jobs gives each its own):
    the scenario's own pages are left out."""
    return all(n.startswith("responsive-") or n in ("console", "requests") for n in run.names)


# the checks the phases after the content pages record (the phone at 360 px and
# the kiosk and flow pages); a job that wants only these loads no content page
AFTER_CONTENT = {"overflow-360", "details-fit", "theme-icon", "theme-toggle", "rain-tracks",
                 "reduced-motion", "reload-fires", "console", "requests"}
AFTER_CONTENT_PREFIX = ("kiosk-", "reason-", "view-", "big-", "layout-", "refresh-", "dst-", "markup-")


def content_wanted(run: Run) -> bool:
    """Whether any check the content pages record is wanted (a job that runs
    only the kiosk and flow checks loads no content page for nothing)."""
    return any(c not in AFTER_CONTENT and not c.startswith(AFTER_CONTENT_PREFIX) for c in run.names)


def page_content(run: Run):
    """A: desktop, light; the content checks, then the details opened (live, rain,
    errors and accuracy; the other scenarios have their own page above)."""
    if run.name not in ("live", "rain", "errors", "accuracy"):
        return
    if not content_wanted(run):
        return
    exp = SCENARIO.get(run.name, {})
    pg = run.page()
    if run.name == "accuracy":
        run.add("location", expect_tokens(pg, "location", exp["location"]))
        run.add("location-detail", expect_tokens(pg, "location-detail", exp["location_detail"]))
        run.add("rain-probability", expect_tokens(pg, "rain-probability", [exp["probability"][run.lang]]))
    else:
        check_common_a(pg, run.name, exp, run.add)
        run.icons["light"] = pg.js('__ui.icons("theme-toggle")')
        check_glance(pg, exp, run.add)
        if exp["radar"] is None:
            run.add("radar-unavailable", visible_one(pg, "radar-unavailable")[1]
                    + [f"{n} rendered [data-test=radar-step] without radar" for n in
                       [sum(e["rendered"] for e in pg.ui("radar-step"))] if n])
            run.add("radar-unavailable-text", radar_unavailable_text_problems(pg, run.lang))
        else:
            check_radar(pg, exp, run.add)
        if exp["now"]:
            check_now(pg, run.add)
            run.add("now-texts", now_texts_problems(pg, run.lang))
            run.add("now-station", expect_tokens(pg, "now-station", NOW_STATION[run.lang]))
            run.add("now-fallback", [f"{n} visible [data-test=now-fallback]: no value fell back here"
                                     for n in [sum(e["visible"] for e in pg.ui("now-fallback"))] if n])
        else:
            run.add("now-unavailable", expect_text(pg, "now-unavailable", FIXED["now.unavailable"][run.lang])
                    + expect_hidden(pg, "now-temp"))
            run.add("now-station", expect_hidden(pg, "now-station"))
        check_chart(pg, exp, run.add)
        if "chart-single-point" in run.names:
            run.add("chart-single-point", chart_single_point(run))
    run.shot(pg, "desktop-light")
    run.done(pg)
    # the details page (?detailed), light
    pg = run.page(query="?detailed")
    check_details(pg, run.name, exp, run.names, run.add)
    if "details-reports-none" in run.names:
        run.add("details-reports-none", report_run.none_problems(pg, run.lang))
    run.add("details-contrast", [f"light: {p}" for p in contrast_problems(pg)])
    run.shot(pg, "desktop-details")
    run.done(pg)
    pg = run.page(scheme="dark", query="?detailed")
    pg.js("__ui.openDetails()")
    pg.settle()
    run.add("details-contrast", [f"dark: {p}" for p in contrast_problems(pg)])
    run.done(pg)
    if run.name == "accuracy":
        return
    # B: desktop, dark
    pg = run.page(scheme="dark")
    run.add("theme-dark", theme_problems(pg.js("__ui.page()"), "dark"))
    run.icons["dark"] = pg.js('__ui.icons("theme-toggle")')
    run.add("contrast-dark", contrast_problems(pg))
    run.shot(pg, "desktop-dark")
    run.done(pg)


# one function per scenario (each next to the checks it uses); run_pages
# dispatches on this table, then runs the parts shared by the scenarios
PAGES = {
    "wizard": run_wizard,
    "fallback": page_fallback,
    "sky": run_sky,
    "report": report_run.run,
    "report-glance": report_run.run,
    "unconfigured": page_unconfigured,
    "live": page_content,
    "rain": page_content,
    "errors": page_content,
    "accuracy": page_content,
}


def page_phone_360(run: Run):
    """C: phone, 360 px: the big view, then the details page (opened)."""
    if run.name not in ("live", "rain", "errors", "unconfigured", "accuracy"):
        return
    if not any(c in run.names for c in ("overflow-360", "details-fit")):
        return  # a job that wants neither check loads no phone page
    for query in ("", "?detailed"):
        pg = run.page(width=360, height=740, query=query)
        pg.js("__ui.openDetails()")
        pg.settle()
        info = pg.js("__ui.page()")
        where = "the details page" if query else "the big view"
        run.add("overflow-360", [] if info["sw"] <= 361 and info["iw"] <= 361 else
                [f"{where}: page is {info['sw']} px wide at 360 px (horizontal scrolling): {pg.js('__ui.overflowing()')}"])
        if query:
            run.add("details-fit", [f"at 360 px: {p}" for p in pg.js('__ui.sticksOut("details")')])
        run.shot(pg, f"phone-360{'-details' if query else ''}")
        run.done(pg)


def page_unconfigured_dark(run: Run):
    """The unconfigured scenario's dark part (B: desktop, dark)."""
    pg = run.page(scheme="dark")
    run.add("setup-texts", setup_texts_problems(pg, run.lang))
    run.add("theme-dark", theme_problems(pg.js("__ui.page()"), "dark"))
    run.icons["dark"] = pg.js('__ui.icons("theme-toggle")')
    run.add("contrast-dark", contrast_problems(pg))
    run.done(pg)


def page_kiosk_and_common(run: Run):
    """The checks shared by the scenarios: the theme toggle's icon, the kiosk view
    (live and rain), the toggle and the reasons flows, the views, the big view's
    labels, the tile layout per width, the refresh failures and the reduced motion."""
    if "theme-icon" in run.names:
        run.add("theme-icon", theme_icon_problems(run.icons))
    kiosk_wanted = any(f"kiosk-{w}x{h}" in run.names for w, h in KIOSK_SIZES)
    if run.name in ("live", "rain") and kiosk_wanted:
        for size in KIOSK_SIZES:
            pg = run.page(width=size[0], height=size[1], query="?kiosk")
            check_kiosk(pg, SCENARIO.get(run.name, {}), size, run.add)
            if f"kiosk-chart-{size[0]}x{size[1]}" in run.names:
                run.add(f"kiosk-chart-{size[0]}x{size[1]}", kiosk_chart_problems(pg, size))
            run.add(f"kiosk-fill-{size[0]}x{size[1]}", kiosk_fill_problems(pg, SCENARIO.get(run.name, {}), size))
            run.add(f"kiosk-room-{size[0]}x{size[1]}", kiosk_room_problems(pg, size))
            run.shot(pg, f"kiosk-{size[0]}x{size[1]}", full=False)
            run.done(pg)
    if "kiosk-turn" in run.names:  # a tablet turned while the big view is open (turn.py)
        run.add("kiosk-turn", kiosk_turn(run))
    if "theme-toggle" in run.names:
        run.add("theme-toggle", theme_toggle(run))
    if any(n.startswith("reason-") for n in run.names):
        run_reasons(run)
    if "view-default" in run.names:
        run_views(run)
    if any(n in run.names for n in ("big-labels", "big-headline", "big-hierarchy", "rain-tracks", "big-tracks",
                                    "view-label")):
        run_big(run)
    for w in LAYOUT_COLUMNS:
        if f"layout-{w}" in run.names:
            pg = run.page(width=w, height=740 if w < 600 else 900)
            run.add(f"layout-{w}", layout_problems(pg, w))
            run.shot(pg, f"layout-{w}")
            run.done(pg)
    if "refresh-render-error" in run.names:
        run.add("refresh-render-error", refresh_render_error(run))
    if "refresh-config-retry" in run.names:
        run.add("refresh-config-retry", refresh_config_retry(run))
    if "reload-fires" in run.names:  # the timed page reload (reload.py)
        run.add("reload-fires", reload_fires(run))
    if "refresh-keeps-old" in run.names:  # a failed refresh keeps the last good data (outdated.py)
        run.add("refresh-keeps-old", refresh_keeps_old(run))
    if "reduced-motion" in run.names:
        pg = run.page(reduced=True)
        time.sleep(0.3)
        running = pg.js("__ui.animations()")
        run.add("reduced-motion", [f"animations still running with prefers-reduced-motion: {running}"] if running else [])
        run.done(pg)
    if "dst-radar-labels" in run.names:  # the rain page at the CEST->CET switch (clock.py)
        run.add("dst-radar-labels", dst_radar_labels(run))
    if "dst-chart-x-labels" in run.names:
        run.add("dst-chart-x-labels", dst_chart_x_labels(run))
    if "markup-api" in run.names:  # the API texts with HTML markup shown as text (markup.py)
        run.add("markup-api", markup_api(run))
    run_responsive(run)  # the responsive sweeps this run wants (responsive.py)

    own = run.base + "/"
    foreign = sorted({u for u in run.requests if not (u.startswith(own) or u.startswith("data:"))})
    run.add("requests", [f"request outside the app: {u}" for u in foreign])
    run.add("console", list(dict.fromkeys(run.errors))[:8])


def layout_problems(pg: UIPage, w: int) -> list[str]:
    """The big view's tiles at a page width (the detailed view is the details
    page, so the tile grid is the big view's): glance, Now and the chart
    visible, the glance first (top left), no tile overlapping another, no
    horizontal scrolling."""
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
