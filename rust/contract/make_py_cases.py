"""Reference results from the Python app for the Rust unit tests (run once; outputs committed).

Runs inside the Python image (Python 3.12, the app's own code):

    podman run --rm --network=none --userns=keep-id --user 1000:1000 -v "$PWD":/w -w /w \\
        localhost/wetter_weather python rust/contract/make_py_cases.py

Writes ``fixtures/py_cases/``:

* ``sum.json``: Python 3.12's ``sum()`` of float lists (compensated
  summation, not plain left-to-right addition).
* ``hypot.json``: ``math.hypot`` on radar-like distances (cell offset
  minus a fractional location, times the cell size).
* ``radar_frames.json``: ``app.brightsky_client._decode_grid`` on valid,
  oversized ("zip bomb"), truncated and broken frames: either the decoded
  values (as a count and checksum) or "error".
"""
from __future__ import annotations

import base64
import json
import math
import pathlib
import random
import struct
import sys
import zlib

sys.path.insert(0, ".")
from app.brightsky_client import _decode_grid  # noqa: E402
from app.upstream import SourceError  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent / "fixtures" / "py_cases"
rng = random.Random(20260930)


def bits(x: float) -> int:
    return struct.unpack("<Q", struct.pack("<d", x))[0]


def sums():
    lists = [[0.1, 0.2, 0.3], [0.5, 0.3, 0.2], [0.3, 0.2], [0.1] * 10, [1e16, 1.0, -1e16],
             [0.7, 0.2, 0.1], [2.0, 1.0, 1.0], [0.0], [], [-0.0], [0.5, 0.25]]
    for _ in range(3000):
        n = rng.randint(1, 6)
        kind = rng.random()
        if kind < 0.4:
            lists.append([round(rng.uniform(0, 1), rng.randint(1, 3)) for _ in range(n)])
        elif kind < 0.7:
            lists.append([rng.uniform(-100, 100) for _ in range(n)])
        else:  # weight * signal products like combine_signals
            lists.append([rng.choice([0.5, 0.3, 0.2, 0.6, 0.4, 1 / 3]) * rng.choice([0.0, 100.0, 60.0, 34.69387755102041, rng.uniform(0, 100)]) for _ in range(n)])
    return [{"values": [bits(v) for v in xs], "sum": bits(sum(xs))} for xs in lists]


def hypots():
    out = []
    for _ in range(4000):
        loc = rng.uniform(0, 400)
        cell = rng.randint(0, 400)
        loc2 = rng.uniform(0, 400)
        cell2 = rng.randint(0, 400)
        km = rng.choice([1.0, 1.0, 0.5, 2.0, rng.uniform(0.1, 3)])
        dx, dy = (cell - loc) * km, (cell2 - loc2) * km
        out.append({"dx": bits(dx), "dy": bits(dy), "hypot": bits(math.hypot(dx, dy))})
    for dx, dy in [(3.0, 4.0), (0.0, 0.0), (-3.0, 4.0), (1.0, 0.0), (0.498, 0.26), (1e-300, 1e-300)]:
        out.append({"dx": bits(dx), "dy": bits(dy), "hypot": bits(math.hypot(dx, dy))})
    return out


def frames():
    cases = []

    def add(name, encoded, n_cells):
        try:
            grid = _decode_grid(encoded, n_cells)
            result = {"len": len(grid), "sum": sum(grid), "weighted": sum(i * v for i, v in enumerate(grid)) % 1_000_000_007}
        except SourceError:
            result = "error"
        cases.append({"name": name, "encoded": encoded, "n_cells": n_cells, "result": result})

    def enc(raw: bytes) -> str:
        return base64.b64encode(raw).decode()

    grid = struct.pack("<16H", *range(0, 1600, 100))
    good = zlib.compress(grid)
    add("valid 4x4", enc(good), 16)
    add("valid, level 9", enc(zlib.compress(grid, 9)), 16)
    add("all zeros 401x401", enc(zlib.compress(bytes(401 * 401 * 2))), 401 * 401)
    add("one byte too long (odd)", enc(zlib.compress(grid + b"\x00")), 16)
    add("one cell too many", enc(zlib.compress(grid + b"\x00\x00")), 16)
    add("one cell too few", enc(zlib.compress(grid[:-2])), 16)
    add("zip bomb (100 MB of zeros)", enc(zlib.compress(bytes(100_000_000), 9)), 16)
    add("truncated stream (last 4 bytes cut)", enc(good[:-4]), 16)
    add("truncated stream (half)", enc(good[: len(good) // 2]), 16)
    add("trailing bytes after the stream", enc(good + b"garbage"), 16)
    add("not zlib", enc(b"hello world, not zlib"), 16)
    add("raw deflate without zlib header", enc(zlib.compress(grid)[2:-4]), 16)
    add("empty", "", 16)
    add("bad base64 characters", "!!!!", 16)
    add("base64 without padding", enc(good).rstrip("="), 16)
    add("base64 with a newline", enc(good)[:8] + "\n" + enc(good)[8:], 16)
    add("zero cells, empty grid", enc(zlib.compress(b"")), 0)
    for i in range(20):
        n = rng.randint(1, 3000)
        vals = [rng.choice([0, 0, 0, 1, 5, 20, 65535]) for _ in range(n)]
        add(f"random {i}", enc(zlib.compress(struct.pack(f"<{n}H", *vals))), n)
    return cases


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    header = f"Python {sys.version.split()[0]}"
    for name, data in (("sum", sums()), ("hypot", hypots()), ("radar_frames", frames())):
        (OUT / f"{name}.json").write_text(json.dumps({"generated_by": header, "cases": data}) + "\n")
        print(f"wrote {name}.json: {len(data)} cases")
