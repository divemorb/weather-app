#!/usr/bin/env python3
"""UI contract: the web page in headless Chromium against the Rust app.

Per scenario the Rust app starts; headless Chromium loads the page in English
and German with the clock frozen at the scenario's "now" and the browser in
UTC. Checks read what the page shows through data-test hooks: content, not
layout. Generic checks: no console errors or CSP violations, same-origin
requests only, WCAG AA contrast in both themes, no overflow at 360 px, the
size budget, and bad data not stopping the page (cdp.Page.fake).
"""
from __future__ import annotations

import argparse
import json
import os
import math
import calendar
import fnmatch
import importlib.util
import pathlib
import re
import socket
import subprocess
import sys
import tempfile
import time
import types

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
STATIC = REPO / "app" / "static"
sys.path.insert(0, str(REPO / "rust" / "contract"))
sys.path.append(str(HERE))
# This file is a run.py too (the contract suite has one as well, loaded by path
# as "contract_run" above in scenario). When run as a script it is "__main__",
# but workers.worker_main does a deferred "from run import parse_args"; register
# this module under the name "run" so that import finds this entry, not the
# contract one (contract/ is first on sys.path).
sys.modules["run"] = sys.modules[__name__]

from cdp import Browser  # noqa: E402
from expect import BUDGET_BYTES, LOCALES  # noqa: E402
from names import UI_SCENARIOS, SCENARIO_LANGS, all_names, check_names, unit_files  # noqa: E402
from scenario import Results, run_scenario  # noqa: E402
import workers  # noqa: E402
from workers import build_jobs, worker_main  # noqa: E402

ALLOWED_EXT = {".html", ".js", ".css"}


# --- unit tests, static files -------------------------------------------------

def run_unit(res: Results, selected):
    """The JS unit tests (node --test per file); a failing test records the
    file's "not ok" and detail lines under its check name."""
    for path in unit_files():
        if not selected(f"unit/{path.name}"):
            continue
        r = subprocess.run(["node", "--test", str(path)], cwd=REPO, capture_output=True, text=True, timeout=120)
        out = r.stdout + r.stderr
        if r.returncode == 0:
            res.add(f"unit/{path.name}", [])
            continue
        lines = [l.strip() for l in out.splitlines()]
        failed = [l for l in lines if l.startswith("not ok")]
        detail = [l for l in lines if re.match(r"(error|expected|actual|code):", l) or "Error" in l][:6]
        res.add(f"unit/{path.name}", (failed[:6] + detail) or [out[-600:]])


def check_static(res: Results, static: pathlib.Path):
    """app/static: within the size budget, one flat directory of .html/.js/.css."""
    files = sorted(static.iterdir())
    total = sum(p.stat().st_size for p in files if p.is_file())
    res.add("budget", [] if total <= BUDGET_BYTES else
            [f"app/static is {total / 1024:.1f} KB, budget {BUDGET_BYTES // 1024} KB"])
    bad = [p.name for p in files if p.is_dir() or p.suffix not in ALLOWED_EXT]
    res.add("static-files", [f"{n}: the Rust app serves one flat directory of .html/.js/.css files only" for n in bad])


# --- main -----------------------------------------------------------------

SANDBOX_ENV = "WETTER_UITEST_SANDBOX"  # set by the watchdog in Qwen's sandbox only
SANDBOX_MAX_SCENARIOS = 3


def sandbox_refusal(args, scenarios, langs) -> str | None:
    """In Qwen's sandbox a run covers at most SANDBOX_MAX_SCENARIOS scenarios:
    the full suite is the watchdog's (it runs it after the attempt), and a
    full run there costs 12 minutes of the attempt. None, or why refused
    and what to run instead."""
    if not os.environ.get(SANDBOX_ENV):
        return None
    chosen = [sc for sc in scenarios
              if any(args.selected(f"{sc}/{lang}/{c}") for lang in SCENARIO_LANGS.get(sc, ["en", "de"])
                     if lang in langs for c in check_names(sc, lang))]
    if args.scenario and len(chosen) <= SANDBOX_MAX_SCENARIOS:
        return None
    what = (f"{len(chosen)} scenarios ({' '.join(chosen)})" if args.scenario
            else "the full suite (no --scenario)")
    return (f"uitest: not run. This run would cover {what}; in this sandbox a run covers at most "
            f"{SANDBOX_MAX_SCENARIOS} scenarios, chosen with --scenario.\n"
            "The full suite takes about 12 minutes, and the watchdog runs it anyway after you finish, "
            "so don't run it yourself. Run the scenarios your change touches, output into a file, e.g.:\n"
            "  python3 rust/uitest/run.py --scenario live > /tmp/ui.log 2>&1; tail -3 /tmp/ui.log\n"
            "then read the details with `grep -A8 '^FAIL' /tmp/ui.log` (don't run it again to see other lines).\n"
            "Single checks: --only 'live/en/glance-*' (with --scenario); all check names: --list.")


def parse_args(argv: list[str] | None = None):
    """The command line; main adds args.selected (the --only filter) afterwards."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--binary", default="/target/debug/wetter", help="the Rust binary")
    ap.add_argument("--scenario", nargs="*", choices=UI_SCENARIOS, help="only these scenarios")
    ap.add_argument("--lang", nargs="*", choices=list(LOCALES), help="only these languages")
    ap.add_argument("--require", nargs="*", default=["*"],
                    help="check patterns that must pass (fnmatch, * crosses /); a pattern with a leading ! "
                         "excludes (a later step's checks); others are reported only")
    ap.add_argument("--shots", metavar="DIR", help="save screenshots there (for a design review)")
    ap.add_argument("--no-unit", action="store_true", help="skip the JS unit tests")
    ap.add_argument("--only", nargs="+", metavar="PATTERN",
                    help="run only the checks matching these patterns (fnmatch, * crosses /, e.g. "
                         "'sky/en/contrast-snow-*'); scenarios without a match don't start, sky skips the rest")
    ap.add_argument("--static", metavar="DIR", type=pathlib.Path,
                    help="serve this folder instead of app/static (planted faults: faults.py)")
    ap.add_argument("--list", action="store_true", help="list the checks and exit")
    ap.add_argument("--backend-log", default=None, help="file for the app's output (default: discard)")
    ap.add_argument("--workers", type=int, default=0,
                    help="the number of worker processes for the scenarios (default: min(12, the CPUs "
                         "available), never more than 16; 1: one after another)")
    ap.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)  # the worker processes
    ap.add_argument("--worker-index", type=int, default=0, help=argparse.SUPPRESS)
    # the first worker index (faults.py runs several run.py at once: disjoint port ranges)
    ap.add_argument("--worker-offset", type=int, default=0, help=argparse.SUPPRESS)
    return ap.parse_args(argv)


def report(res: Results, args, scenarios: list[str], langs: list[str]) -> int:
    """The PASS/FAIL lines and the summary, in the order of all_names():
    identical no matter which process ran the checks."""
    passed = failed = required_failed = 0
    expected = [n for n in all_names(scenarios, langs)
                if args.selected(n) and not (args.no_unit and n.startswith("unit/"))]
    for name in expected:
        problems = res.problems.get(name)
        if problems is None:
            problems = ["not checked (harness error before this check)"]
        if not problems:
            passed += 1
            print(f"PASS {name}")
            continue
        failed += 1
        required = (any(fnmatch.fnmatch(name, p) for p in args.require if not p.startswith("!"))
                    and not any(fnmatch.fnmatch(name, p[1:]) for p in args.require if p.startswith("!")))
        required_failed += required
        print(f"FAIL {name}{'' if required else ' (not required yet)'}")
        for p in problems[:8]:
            print(f"     {p}")
    print(f"uitest: {passed} passed, {failed} failed, {required_failed} of them required")
    return 1 if required_failed else 0


def main() -> int:
    """Run the checks (workers or serial) and report; exit 1 iff a required check failed."""
    args = parse_args()
    if args.worker:  # a worker process: the jobs come in on stdin
        return worker_main()
    scenarios = args.scenario or UI_SCENARIOS
    langs = args.lang or list(LOCALES)
    args.selected = lambda name: not args.only or any(fnmatch.fnmatch(name, p) for p in args.only)
    if args.list:
        print("\n".join(n for n in all_names(scenarios, langs) if args.selected(n)))
        return 0
    refused = sandbox_refusal(args, scenarios, langs)
    if refused:
        print(refused, file=sys.stderr)
        return 2
    args.workers = args.workers if args.workers > 0 else workers.default_workers()
    if args.shots:
        pathlib.Path(args.shots).mkdir(parents=True, exist_ok=True)

    res = Results()
    check_static(res, args.static or STATIC)
    if not args.no_unit:
        run_unit(res, args.selected)
    if args.workers == 1:
        args.log = open(args.backend_log, "a") if args.backend_log else subprocess.DEVNULL
        try:
            browsers = {lang: Browser(lang=LOCALES[lang]) for lang in langs}
            for name in scenarios:
                run_scenario(name, browsers, args, res)
        finally:
            for b in browsers.values():
                b.close()
    else:
        jobs, job_checks = build_jobs(args, scenarios, langs)
        problems = workers.run_jobs(args, jobs, job_checks)
        for name, ps in problems.items():
            res.add(name, ps)
    return report(res, args, scenarios, langs)


if __name__ == "__main__":
    sys.exit(main())
