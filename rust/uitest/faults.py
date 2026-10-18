#!/usr/bin/env python3
"""Planted faults: proof that the UI harness still sees the defects in faults.json.

Each fault edits a copy of app/static and runs run.py on it (--static, only
the fault's scenarios, languages and checks); every pattern in its must_fail
has to match at least one failing check, else the fault is MISSED and the
run fails. A faster or rewritten harness (parallel, frozen animations, fewer
screenshots) must keep every fault caught; the full suite must still pass on
the real page.

    python3 rust/uitest/faults.py --binary /target/debug/wetter [--require PATTERN ...] [--fault NAME ...]

--require: which faults must be caught, as in the other harnesses (fnmatch on
"fault/<name>", a leading ! excludes; default all). --discover prints every
failing check per fault (to choose must_fail). --gaps runs the "gaps" list
instead: defects today's checks don't see; a caught one belongs in "faults".
Output ends with "faults: N caught, M missed, K of them required"; exit 1
when a required fault is missed or doesn't apply any more (its find text is
gone: update faults.json).
"""
from __future__ import annotations

import argparse
import concurrent.futures
import fnmatch
import json
import pathlib
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
JOBS = 6  # faults run at once; each run.py gets 2 workers of its own (ports: worker_ports)
STATIC = HERE.parent.parent / "app" / "static"


def plant(fault: dict, dest: pathlib.Path) -> None:
    shutil.copytree(STATIC, dest)
    for e in fault["edits"]:
        path = dest / e["file"]
        text = path.read_text()
        if "append" in e:
            text += e["append"]
        else:
            n = text.count(e["find"])
            if n != 1:
                raise ValueError(f"{e['file']}: the find text occurs {n} times, expected once: {e['find']!r}")
            text = text.replace(e["find"], e["replace"])
        path.write_text(text)


def worker_ports(slot: int) -> list[str]:
    """run.py options for a fault in this slot: 2 workers whose indices (and so
    port ranges) no other slot and no plain run.py (indices 0-7) uses."""
    return ["--workers", "2", "--worker-offset", str(8 + 2 * slot)]


def run_fault(fault: dict, binary: str, slot: int = 0) -> tuple[list[str], str]:
    """The failing checks of the run on the planted copy, and the output."""
    with tempfile.TemporaryDirectory(prefix="fault-") as tmp:
        static = pathlib.Path(tmp) / "static"
        plant(fault, static)
        cmd = [sys.executable, str(HERE / "run.py"), "--binary", binary, "--no-unit", "--static", str(static),
               "--scenario", *fault["scenario"], *worker_ports(slot)]
        if fault.get("lang"):
            cmd += ["--lang", *fault["lang"]]
        if fault.get("only"):
            cmd += ["--only", *fault["only"]]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    out = r.stdout + r.stderr
    return re.findall(r"^FAIL (\S+)", out, re.M), out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--binary", default="/target/debug/wetter")
    ap.add_argument("--fault", nargs="*", help="only these faults")
    ap.add_argument("--discover", action="store_true", help="print every failing check per fault")
    ap.add_argument("--require", nargs="*", default=["*"], help="fault/<name> patterns that must be caught")
    ap.add_argument("--gaps", action="store_true", help="run the gaps list (not required)")
    ap.add_argument("--jobs", type=int, default=JOBS, help="faults run at once")
    args = ap.parse_args()
    faults = json.loads((HERE / "faults.json").read_text())["gaps" if args.gaps else "faults"]
    if args.fault:
        unknown = set(args.fault) - {f["name"] for f in faults}
        if unknown:
            sys.exit(f"unknown faults: {sorted(unknown)}")
        faults = [f for f in faults if f["name"] in args.fault]
    def required(name):
        n = f"fault/{name}"
        return (not args.gaps and any(fnmatch.fnmatch(n, p) for p in args.require if not p.startswith("!"))
                and not any(fnmatch.fnmatch(n, p[1:]) for p in args.require if p.startswith("!")))

    slots: queue.Queue[int] = queue.Queue()
    for s in range(max(1, args.jobs)):
        slots.put(s)

    def in_slot(fault):
        slot = slots.get()
        try:
            t0 = time.time()
            failed, out = run_fault(fault, args.binary, slot)
            return failed, out, time.time() - t0
        finally:
            slots.put(slot)

    caught = missed = required_missed = 0
    pool = concurrent.futures.ThreadPoolExecutor(max(1, args.jobs))
    futures = [pool.submit(in_slot, f) for f in faults]
    for fault, future in zip(faults, futures):  # reported in faults.json order
        try:
            failed, out, secs = future.result()
        except (ValueError, subprocess.TimeoutExpired) as exc:
            missed += 1
            required_missed += required(fault["name"])
            print(f"MISSED {fault['name']}: not run: {exc}")
            continue
        lacking = [p for p in fault["must_fail"] if not any(fnmatch.fnmatch(c, p) for c in failed)]
        took = f"{secs:.0f} s"
        if lacking:
            missed += 1
            required_missed += required(fault["name"])
            tail = "" if failed else " | " + " / ".join(out.strip().splitlines()[-3:])
            print(f"MISSED {fault['name']}{'' if required(fault['name']) else ' (not required)'} "
                  f"({fault['why']}, {took}): no failing check matches {lacking}; "
                  f"failed: {failed[:8] or 'none'}{tail}")
        else:
            caught += 1
            print(f"CAUGHT {fault['name']} ({took}): {', '.join(failed[:6])}{' …' if len(failed) > 6 else ''}")
        if args.discover:
            for c in failed:
                print(f"     {c}")
    pool.shutdown()
    print(f"faults: {caught} caught, {missed} missed, {required_missed} of them required")
    return 1 if required_missed else 0


if __name__ == "__main__":
    sys.exit(main())
