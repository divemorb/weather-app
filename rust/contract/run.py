#!/usr/bin/env python3
"""Contract suite: prove the Rust backend answers exactly as the goldens record.

For each scenario (``scenarios.py``) a fresh backend is started (``backend.py``)
with a frozen clock (``WETTER_FAKE_NOW``), a temporary database and a generated
config whose upstream URLs point at a fake upstream (``fakeup.py``); the
responses are normalized and compared with the goldens in ``golden/`` (frozen,
recorded with ``--update`` and reviewed as a git diff). The binary must honour
``WEATHER_CONFIG``, ``DATABASE_PATH``, ``LATITUDE``/``LONGITUDE``/``TIMEZONE``,
``ALLOWED_HOSTS``, ``USE_ACCURACY_WEIGHTS``, ``WETTER_FAKE_NOW``, ``BIND_ADDR``,
``STATIC_DIR``; it runs the initial refresh before serving, so ``/healthz``
answering means the refresh is done. Comparison: parsed JSON with strict types
(``1`` is not ``1.0``) and exact floats; status codes; the security/caching
headers; static files by hash. Normalized: ``last_error`` (null or not),
``next_run_utc`` (null or not), the ``msg`` of 422 details. Per scenario the
requests sent upstream are compared too, and with ``--budget-mb`` the peak
memory (VmHWM).

    # in the sandbox (after `cargo build`):
    python3 rust/contract/run.py --backend rust --binary /target/debug/wetter
    # only some cases, e.g. while the skeleton is being built:
    python3 rust/contract/run.py --backend rust --binary /target/debug/wetter --require 'unconfigured:static/*'
    # list the cases:
    python3 rust/contract/run.py --list
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from backend import (free_port, make_config, request, seed_db, start_backend,  # noqa: E402
                     stop_backend, wait_ready)
from fakeup import FakeUpstream  # noqa: E402
from scenarios import SCENARIOS  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
GOLDEN = HERE / "golden"
COMPARED_HEADERS = ["content-type", "content-security-policy", "x-content-type-options",
                    "referrer-policy", "cross-origin-resource-policy", "cache-control",
                    "access-control-allow-origin", "allow"]


# --- requests and comparison -------------------------------------------------

def _normalize_json(value, status):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in ("last_error", "next_run_utc") and v is not None:
                out[k] = f"<{k}>"
            elif k == "msg" and status == 422:
                out[k] = "<msg>"
            else:
                out[k] = _normalize_json(v, status)
        return out
    if isinstance(value, list):
        return [_normalize_json(v, status) for v in value]
    return value


def normalize(case: dict, resp: dict) -> dict:
    h = resp["headers"]
    out = {"status": resp["status"], "headers": {k: h[k] for k in COMPARED_HEADERS if k in h}}
    out["headers"]["etag"] = "present" if "etag" in h else "absent"
    mode = case.get("compare")
    body = resp["body"]
    if mode is None:
        mode = "json" if h.get("content-type", "").startswith("application/json") else "text"
    if mode == "json":
        try:
            out["json"] = _normalize_json(json.loads(body), resp["status"])
        except ValueError:
            out["text"] = body.decode("utf-8", "replace")
    elif mode == "text":
        out["text"] = body.decode("utf-8", "replace")
    elif mode == "bytes":
        out["sha256"], out["length"] = hashlib.sha256(body).hexdigest(), len(body)
    return out


def diff(want, got, path="") -> list[str]:
    """Differences with strict types: 1 != 1.0, True != 1."""
    if type(want) is not type(got):
        return [f"{path or '/'}: expected {want!r} ({type(want).__name__}), got {got!r} ({type(got).__name__})"]
    if isinstance(want, dict):
        out = []
        for k in sorted(set(want) | set(got)):
            if k not in got:
                out.append(f"{path}/{k}: missing (expected {want[k]!r})")
            elif k not in want:
                out.append(f"{path}/{k}: unexpected {got[k]!r}")
            else:
                out += diff(want[k], got[k], f"{path}/{k}")
        return out
    if isinstance(want, list):
        if len(want) != len(got):
            return [f"{path}: expected {len(want)} items, got {len(got)}: {got!r}"[:400]]
        return [d for i, (a, b) in enumerate(zip(want, got)) for d in diff(a, b, f"{path}[{i}]")]
    return [] if want == got else [f"{path or '/'}: expected {want!r}, got {got!r}"]


# --- one scenario --------------------------------------------------------

def run_scenario(args, sc: dict) -> dict:
    """Returns {"cases": {name: normalized | {"error": ...}}, "upstream": [...], "memory_kb": n}."""
    fake = FakeUpstream(sc["routes"])
    with tempfile.TemporaryDirectory(prefix="contract-") as tmp:
        tmp = pathlib.Path(tmp)
        db = tmp / "weather.db"
        if sc.get("seed"):
            seed_db(db, sc["seed"], sc["now"])
        env = {"WEATHER_CONFIG": str(make_config(tmp, fake.base)), "DATABASE_PATH": str(db),
               "WETTER_FAKE_NOW": sc["now"], **sc["env"]}
        if args.backend == "external":  # the app runs already (checkpoint: the image)
            port, proc = args.port, None
        else:
            port = free_port()
            proc = start_backend(args, port, env)
        result = {"cases": {}, "upstream": [], "memory_kb": None}
        error = wait_ready(port, proc)
        etags = {}
        for case in sc["cases"]:
            if error:
                result["cases"][case["name"]] = {"error": error}
                continue
            before = len(fake.log)
            try:
                resp = request(port, case, etags)
            except OSError as exc:
                result["cases"][case["name"]] = {"error": f"request failed: {exc!r}"}
                continue
            if "etag" in resp["headers"]:
                etags[case["name"]] = resp["headers"]["etag"]
            if case.get("settle"):
                end = time.monotonic() + 10
                while len(fake.log) == before and time.monotonic() < end:
                    time.sleep(0.05)
                fake.wait_idle(quiet=1.0)
            result["cases"][case["name"]] = normalize(case, resp)
        result["memory_kb"] = stop_backend(proc)
        result["upstream"] = fake.requests()
    fake.stop()
    return result


# --- main ----------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", choices=["rust", "external"], default="rust",
                    help="external: test an app that already runs on --port (started with --print-env's variables)")
    ap.add_argument("--port", type=int, default=8000, help="port of the external app")
    ap.add_argument("--print-env", metavar="SCENARIO",
                    help="print the environment an external app needs for SCENARIO and exit")
    ap.add_argument("--binary", default="/target/debug/wetter", help="the Rust binary (--backend rust)")
    ap.add_argument("--scenario", nargs="*", help="only these scenarios")
    ap.add_argument("--require", nargs="*", default=["*"],  # "!pattern" excludes
                    help="case patterns (scenario:case) that must pass; others are reported only")
    ap.add_argument("--budget-mb", type=float, help="fail a scenario whose peak memory is above this")
    ap.add_argument("--update", action="store_true", help="write the goldens from the Rust backend (review the git diff)")
    ap.add_argument("--list", action="store_true", help="list the cases and exit")
    ap.add_argument("--backend-log", default=None, help="file for the backend's output (default: discard)")
    args = ap.parse_args()
    scenarios = [s for s in SCENARIOS if not args.scenario or s["name"] in args.scenario]
    if args.print_env or args.backend == "external":
        names = [args.print_env] if args.print_env else [s["name"] for s in scenarios]
        for sc in (s for s in SCENARIOS if s["name"] in names):
            if sc["routes"] or sc.get("seed"):
                sys.exit(f"scenario {sc['name']} needs the fake upstream or a seeded database; "
                         "only self-contained scenarios (unconfigured) run against an external app")
    if args.print_env:
        sc = next(s for s in SCENARIOS if s["name"] == args.print_env)
        for k, v in {"WETTER_FAKE_NOW": sc["now"], **sc["env"]}.items():
            print(f"{k}={v}")
        return 0
    if args.list:
        for sc in scenarios:
            for case in sc["cases"]:
                print(f"{sc['name']}:{case['name']}")
        return 0
    if args.update and args.backend != "rust":
        sys.exit("goldens are recorded from the Rust backend (--backend rust)")
    args.log = open(args.backend_log, "a") if args.backend_log else subprocess.DEVNULL

    passed = failed = required_failed = 0

    def report(name, problems):
        nonlocal passed, failed, required_failed
        if not problems:
            passed += 1
            print(f"PASS {name}")
            return
        failed += 1
        required = (any(fnmatch.fnmatch(name, p) for p in args.require if not p.startswith("!"))
                    and not any(fnmatch.fnmatch(name, p[1:]) for p in args.require if p.startswith("!")))
        required_failed += required
        print(f"FAIL {name}{'' if required else ' (not required yet)'}")
        for p in problems[:8]:
            print(f"     {p}")

    for sc in scenarios:
        result = run_scenario(args, sc)
        if args.update:
            GOLDEN.mkdir(exist_ok=True)
            errors = {n: c["error"] for n, c in result["cases"].items() if "error" in c}
            if errors:
                sys.exit(f"{sc['name']}: {errors}")
            # an entry that still compares equal stays as recorded (key order
            # included), so the git diff shows only the cases that changed
            path = GOLDEN / f"{sc['name']}.json"
            old = json.loads(path.read_text()) if path.exists() else {"cases": {}}
            cases = {n: old["cases"][n] if n in old["cases"] and not diff(old["cases"][n], c) else c
                     for n, c in result["cases"].items()}
            upstream = (old["upstream"] if "upstream" in old and not diff(old["upstream"], result["upstream"])
                        else result["upstream"])
            changed = sum(cases[n] is c for n, c in result["cases"].items()) + (upstream is result["upstream"])
            golden = {"now": sc["now"], "upstream": upstream, "cases": cases}
            path.write_text(json.dumps(golden, indent=1, ensure_ascii=False) + "\n")
            print(f"wrote golden/{sc['name']}.json ({len(cases)} cases, {changed} new or changed)")
            continue
        golden_file = GOLDEN / f"{sc['name']}.json"
        if not golden_file.exists():  # a new scenario before its goldens were recorded
            report(f"{sc['name']}:golden", [f"no golden/{golden_file.name} yet (record it with --update)"])
            continue
        golden = json.loads(golden_file.read_text())
        for name, want in golden["cases"].items():
            got = result["cases"].get(name, {"error": "case not run"})
            report(f"{sc['name']}:{name}", [got["error"]] if "error" in got else diff(want, got))
        report(f"{sc['name']}:upstream-requests", diff(golden["upstream"], result["upstream"], "/upstream"))
        if args.budget_mb and result["memory_kb"] is not None:
            peak = result["memory_kb"] / 1024
            report(f"{sc['name']}:memory",
                   [] if peak <= args.budget_mb else [f"peak {peak:.1f} MB > budget {args.budget_mb} MB"])
        print(f"     ({sc['name']}: peak memory {result['memory_kb']} kB)")

    if not args.update:
        print(f"contract: {passed} passed, {failed} failed, {required_failed} of them required")
    return 1 if required_failed else 0


if __name__ == "__main__":
    sys.exit(main())
