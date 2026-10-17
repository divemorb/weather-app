#!/usr/bin/env python3
"""Contract suite: prove the Rust backend answers exactly as the goldens record.

For each scenario (``scenarios.py``) a fresh backend is started with a
frozen clock (``WETTER_FAKE_NOW``), a temporary database and a generated
config whose upstream URLs point at a fake upstream (``fakeup.py``). The
responses are normalized and compared with the goldens in ``golden/``.
The goldens were recorded from the Python app (the reference until v2.0,
tag ``python-last``) and are frozen: a change is recorded from the Rust
backend with ``--update`` and reviewed as a git diff.

    # in the sandbox (after `cargo build`):
    python3 rust/contract/run.py --backend rust --binary /target/debug/wetter
    # only some cases, e.g. while the skeleton is being built:
    python3 rust/contract/run.py --backend rust --binary /target/debug/wetter --require 'unconfigured:static/*'
    # list the cases:
    python3 rust/contract/run.py --list

What the Rust binary must honour (same as the v1 app, plus three
test/deployment variables): ``WEATHER_CONFIG``, ``DATABASE_PATH``,
``LATITUDE``/``LONGITUDE``/``TIMEZONE``, ``ALLOWED_HOSTS``,
``USE_ACCURACY_WEIGHTS``; ``WETTER_FAKE_NOW`` (frozen clock),
``BIND_ADDR`` (default ``0.0.0.0:8000``), ``STATIC_DIR`` (default
``/app/static``). Like the v1 app it runs the initial refresh before
it starts serving, so ``/healthz`` answering means the refresh is done.

Comparison: parsed JSON with strict types (``1`` is not ``1.0``) and exact
floats; status codes; the security/caching headers; static files by
hash. Normalized: ``last_error`` (null or not), ``next_run_utc`` (null or
not), the ``msg`` of 422 details. Per scenario the requests sent upstream
are compared too, and with ``--budget-mb`` the peak memory (VmHWM).
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import http.client
import json
import os
import pathlib
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from fakeup import FakeUpstream  # noqa: E402
from scenarios import DEFAULT_HEADERS, SCENARIOS  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
GOLDEN = HERE / "golden"
COMPARED_HEADERS = ["content-type", "content-security-policy", "x-content-type-options",
                    "referrer-policy", "cross-origin-resource-policy", "cache-control",
                    "access-control-allow-origin", "allow"]
MODELS = ["icon_d2", "icon_eu", "ecmwf_ifs025", "gfs_seamless", "arome_france", "ukmo_seamless"]


# --- setup -----------------------------------------------------------------

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_config(tmp: pathlib.Path, base: str) -> pathlib.Path:
    """The repo's weather.yaml with the api block pointing at the fake upstream."""
    text = (REPO / "weather.yaml").read_text()
    head = text[: text.index("\napi:")]
    path = tmp / "weather.yaml"
    path.write_text(head + f"""
api:
  brightsky_base_url: "{base}/bs"
  open_meteo_base_url: "{base}/om/v1"
  ensemble_base_url: "{base}/ens/v1"
  nominatim_base_url: "{base}/nom"
  timeout_seconds: 5
""")
    return path


def python_schema() -> str:
    """The v1 (Python) app's schema, frozen at tag python-last."""
    return (HERE / "fixtures" / "python_schema_v3.sql").read_text()


def seed_db(db: pathlib.Path, seed: dict, now: str):
    """A database as the Python app (schema v3) would have left it."""
    con = sqlite3.connect(db)
    con.executescript(python_schema())
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_fh_model_from ON forecast_history (model, valid_from)")
    con.execute("INSERT INTO app_meta (key, value) VALUES ('forecast_history_version', '3')")
    if seed.get("location"):
        con.execute("INSERT INTO app_meta (key, value) VALUES ('location', ?)", (json.dumps(
            {"latitude": 52.52, "longitude": 13.405, "timezone": "Europe/Berlin", "label": "Berlin"}),))
    hour = datetime.fromisoformat(now.replace("Z", "+00:00")).replace(minute=0, second=0)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    skill = {"icon_d2": 9, "icon_eu": 6, "ecmwf_ifs025": 2, "gfs_seamless": 5, "arome_france": 8,
             "ukmo_seamless": 3}  # right in about skill/10 of the hours
    insert = ("INSERT INTO forecast_history (model, issued_at, valid_from, valid_to, precip_mm,"
              " observed_mm) VALUES (?, ?, ?, ?, ?, ?)")

    def row(model, start, precip, observed):
        return (model, (start - timedelta(hours=1)).strftime(fmt), start.strftime(fmt),
                (start + timedelta(hours=1)).strftime(fmt), precip, observed)

    for model in MODELS:
        # hours older than 48 h: the startup backfill (last 48 h) leaves them alone
        n_rows = 10 if seed.get("history") == "gate" and model == "ukmo_seamless" else 60
        for i in range(49, 49 + n_rows):
            rain = i % 3 == 0
            observed = 0.5 if rain else 0.0
            right = i % 10 < skill[model]
            forecast_rain = rain if right else not rain
            precip = 0.2 + 0.1 * (i % 3) if forecast_rain else 0.05 * (i % 2)
            con.execute(insert, row(model, hour - timedelta(hours=i), precip, observed))
        # recent hours without observation: the backfill fills them from the station
        for i in range(2, 14):
            con.execute(insert, row(model, hour - timedelta(hours=i), 0.1 * (i % 4), None))
        old = hour - timedelta(days=31)  # outside the 30-day window
        con.execute("INSERT INTO forecast_history (model, issued_at, valid_from, valid_to, precip_mm,"
                    " observed_mm) VALUES (?, ?, ?, ?, 5.0, 0.0)",
                    (model, old.strftime(fmt), old.strftime(fmt), (old + timedelta(hours=1)).strftime(fmt)))
    if seed.get("reports"):
        seed_reports(con, hour)
    con.commit()
    con.close()


#: (hours back, minute, kind, intensity, confirms) for the "reports" seed:
#: two reports in one hour (the newer decides), a confirmation, an hour
#: the startup backfill observes, one outside the 30-day window (dropped by
#: the first new report). Ids 1-7 in this order.
SEEDED_REPORTS = [
    (31 * 24, 10, "rain", None, 0),
    (54, 5, "rain", "light", 0),
    (57, 15, "thunderstorm", None, 0),
    (57, 45, "partly-cloudy", None, 0),
    (62, 40, "rain", "heavy", 0),
    (65, 30, "cloudy", None, 1),
    (3, 20, "snow", None, 0),
    (-1, 10, "hail", None, 0),  # "in the future" (a clock that jumped back): never the current one
]


def seed_reports(con, hour: datetime) -> None:
    """User reports, for the scenarios with the ``reports`` seed."""
    for back, minute, kind, intensity, confirms in SEEDED_REPORTS:
        at = (hour - timedelta(hours=back)).replace(minute=minute)
        con.execute("INSERT INTO user_reports (kind, intensity, confirms, observed_at) VALUES (?, ?, ?, ?)",
                    (kind, intensity, confirms, at.strftime("%Y-%m-%dT%H:%M:%SZ")))


def start_backend(args, port: int, env: dict) -> subprocess.Popen:
    base_env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG") if k in os.environ}
    full_env = {**base_env, **env}
    full_env.update(BIND_ADDR=f"127.0.0.1:{port}", STATIC_DIR=env.get("STATIC_DIR", str(REPO / "app" / "static")))
    return subprocess.Popen([args.binary], cwd=REPO, env=full_env, stdin=subprocess.DEVNULL,
                            stdout=args.log, stderr=subprocess.STDOUT)


def wait_ready(port: int, proc: subprocess.Popen, timeout: float = 60.0) -> str | None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if proc is not None and proc.poll() is not None:
            return f"backend exited with code {proc.returncode} (see the backend log)"
        try:
            if request(port, {"path": "/healthz"})["status"] == 200:
                return None
        except OSError:
            pass
        time.sleep(0.2)
    return f"backend not ready after {timeout:.0f} s"


def stop_backend(proc: subprocess.Popen | None) -> int | None:
    if proc is None:
        return None
    peak = None
    try:
        for line in pathlib.Path(f"/proc/{proc.pid}/status").read_text().splitlines():
            if line.startswith("VmHWM:"):
                peak = int(line.split()[1])
    except OSError:
        pass
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    return peak


# --- requests and comparison -------------------------------------------------

def request(port: int, case: dict, etags: dict | None = None) -> dict:
    headers = {**DEFAULT_HEADERS, **case.get("headers", {})}
    if case.get("etag_from") and etags:
        headers["If-None-Match"] = etags.get(case["etag_from"], "")
    body = case.get("body")
    data = None if body is None else (body if isinstance(body, str) else json.dumps(body)).encode()
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    conn.putrequest(case.get("method", "GET"), case["path"], skip_host=True, skip_accept_encoding=True)
    for k, v in headers.items():
        if v is not None:
            conn.putheader(k, v)
    if data is not None:
        conn.putheader("Content-Length", str(len(data)))
    conn.endheaders(data)
    resp = conn.getresponse()
    out = {"status": resp.status, "headers": {k.lower(): v for k, v in resp.getheaders()}, "body": resp.read()}
    conn.close()
    return out


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
