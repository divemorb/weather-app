"""Derive the synthetic ``fixtures/rain/`` set from the recorded ``fixtures/live/`` set.

Run once by hand (the outputs are committed); deterministic. The live
recording (2026-09-30 10:25 UTC, Berlin) was dry, so rain is added where
the scenarios need it. Chosen to hit the edge cases of the port, with
``now = 10:50``:

* radar: rain in the 10:55 and 11:00 frames: 0.2 mm in a cell 0.57 km from
  the location (inside the 1 km radius) and 0.5 mm in a cell 2.5 km away
  (outside); 10:55 also has 0.04 mm next to the location (below the
  0.05 mm cell threshold).
* forecast minutely_15, steps 11:00/11:15/11:30/11:45 (the next hour):
  icon_d2 0.35 mm (rain), icon_eu 0.08 (dry), ecmwf_ifs025 exactly 0.1
  (not > 0.1: dry), gfs_seamless has a null step (does not vote),
  arome_france 0.3 (rain), ukmo_seamless 0.05 + 0.06 = 0.11000000000000001
  (rain). Hourly: some rain for the 24 h chart; gfs_seamless hourly
  precipitation is all null (dropped from the chart).
* ensemble at stamp 12:00 (first stamp >= now + 30 min): members 1-17
  0.2 mm, member 18 exactly 0.1 (dry), member 50 null (not counted):
  17 of 49 -> 34.69... %.
"""
from __future__ import annotations

import array
import base64
import json
import pathlib
import zlib

HERE = pathlib.Path(__file__).resolve().parent / "fixtures"
LIVE, RAIN = HERE / "live", HERE / "rain"


def load(name):
    return json.loads((LIVE / f"{name}.json").read_text())


def save(name, data):
    (RAIN / f"{name}.json").write_text(json.dumps(data, indent=1) + "\n")


def radar():
    data = load("radar")
    top, left, bottom, right = data["bbox"]
    width = right - left + 1
    rain = {  # frame timestamp -> [(col, row, units of 0.01 mm)]
        "2026-09-30T10:55:00+00:00": [(199, 200, 20), (202, 200, 50), (200, 200, 4)],
        "2026-09-30T11:00:00+00:00": [(199, 200, 20), (202, 200, 50)],
    }
    for frame in data["radar"]:
        cells = rain.get(frame["timestamp"])
        if not cells:
            continue
        grid = array.array("H")
        grid.frombytes(zlib.decompress(base64.b64decode(frame["precipitation_5"])))
        for col, row, value in cells:
            grid[row * width + col] = value
        frame["precipitation_5"] = base64.b64encode(zlib.compress(grid.tobytes())).decode()
    save("radar", data)


def forecast():
    data = load("forecast")
    m15 = data["minutely_15"]
    steps = {t: i for i, t in enumerate(m15["time"])}
    next_hour = ["2026-09-30T11:00", "2026-09-30T11:15", "2026-09-30T11:30", "2026-09-30T11:45"]
    values = {
        "icon_d2": [0.1, 0.05, 0.0, 0.2],
        "icon_eu": [0.02, 0.02, 0.02, 0.02],
        "ecmwf_ifs025": [0.1, 0.0, 0.0, 0.0],
        "gfs_seamless": [0.0, None, 0.0, 0.0],
        "arome_france": [0.0, 0.0, 0.0, 0.3],
        "ukmo_seamless": [0.05, 0.06, 0.0, 0.0],
    }
    for model, vals in values.items():
        series = m15[f"precipitation_{model}"]
        for t, v in zip(next_hour, vals):
            series[steps[t]] = v
    hourly = data["hourly"]
    hsteps = {t: i for i, t in enumerate(hourly["time"])}
    for model, t, v in [("icon_d2", "2026-09-30T12:00", 0.4), ("icon_d2", "2026-09-30T13:00", 1.2),
                        ("icon_eu", "2026-09-30T13:00", 0.7), ("arome_france", "2026-09-30T15:00", 2.5),
                        ("ukmo_seamless", "2026-10-01T02:00", 0.3)]:
        hourly[f"precipitation_{model}"][hsteps[t]] = v
    hourly["precipitation_gfs_seamless"] = [None] * len(hourly["time"])
    save("forecast", data)


def ensemble():
    data = load("ensemble")
    hourly = data["hourly"]
    idx = hourly["time"].index("2026-09-30T12:00")
    for n in range(1, 51):
        key = f"precipitation_member{n:02d}"
        hourly[key][idx] = 0.2 if n <= 17 else 0.1 if n == 18 else None if n == 50 else 0.0
    save("ensemble", data)


if __name__ == "__main__":
    RAIN.mkdir(exist_ok=True)
    radar()
    forecast()
    ensemble()
    print("wrote", sorted(p.name for p in RAIN.iterdir()))
