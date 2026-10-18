"""Backend lifecycle and seeding for the contract suite: start a fresh
``wetter`` binary per scenario (temp database, generated config pointing at a
fake upstream), seed the database as the v1 app would have left it, and the
HTTP ``request`` helper the health check and the scenario cases send."""
from __future__ import annotations

import http.client
import json
import os
import pathlib
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from scenarios import DEFAULT_HEADERS  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
MODELS = ["icon_d2", "icon_eu", "ecmwf_ifs025", "gfs_seamless", "arome_france", "ukmo_seamless"]


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
