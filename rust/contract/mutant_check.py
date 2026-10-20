#!/usr/bin/env python3
"""Mutant check: proves that the unit tests catch chosen code changes.

Each mutant in mutants.json (found by cargo-mutants and missed by every test
at the time) is applied to a copy of the crate; `cargo test --lib` must then
fail. A mutant whose tests still pass is reported as SURVIVED (exit 1).

    python3 rust/contract/mutant_check.py GROUP      (a key of mutants.json)
    python3 rust/contract/mutant_check.py --list
"""
import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys

CONTRACT = pathlib.Path(__file__).resolve().parent
CRATE = CONTRACT.parent
WORK = pathlib.Path(os.environ.get("MUTANT_CHECK_DIR", "/tmp/mutant-check"))
# A target dir of its own: sharing the crate's would let the main build pick
# up a mutated test binary; /tmp is mounted noexec in the sandbox.
TARGET = os.environ.get("MUTANT_CHECK_TARGET", "/target/mutant-check")
TEST = ["cargo", "test", "--locked", "--offline", "-q", "--lib"]
TIMEOUT_S = 300


def copy_crate():
    """A fresh copy of the crate (sources, manifest, fixtures) under WORK."""
    dest = WORK / "rust"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(CRATE, dest, ignore=shutil.ignore_patterns("target", "uitest", "__pycache__", "golden"))
    return dest


def locate(text, m):
    """The mutant's span as offsets into text, or an error message. The
    span's first line is found by its full text (nearest to the recorded
    line), so tests added elsewhere don't break the lookup."""
    lines = text.splitlines(keepends=True)
    want = m["start"][0] - 1
    hits = [i for i, line in enumerate(lines) if line.rstrip("\n") == m["anchor"]]
    if not hits:
        return None, f"line not found: {m['anchor'].strip()!r} (the code under test changed?)"
    shift = min(hits, key=lambda i: abs(i - want)) - want

    def offset(line, col):
        return sum(len(x) for x in lines[: line - 1 + shift]) + col - 1

    a, b = offset(*m["start"]), offset(*m["end"])
    if text[a:b] != m["original"]:
        return None, f"expected {m['original']!r} at line {m['start'][0] + shift}, found {text[a:b]!r}"
    return (a, b), None


def check(crate, m):
    """KILLED, SURVIVED or ERROR (with a reason) for one mutant."""
    path = crate / m["file"]
    original = path.read_text()
    span, error = locate(original, m)
    if error:
        return "ERROR", error
    a, b = span
    path.write_text(original[:a] + m["replacement"] + original[b:])
    try:
        p = subprocess.run(TEST, cwd=crate, capture_output=True, text=True, timeout=TIMEOUT_S,
                           env={**os.environ, "CARGO_TARGET_DIR": TARGET})
    except subprocess.TimeoutExpired:
        return "KILLED", f"the tests hung (> {TIMEOUT_S} s)"
    finally:
        path.write_text(original)
    if "could not compile" in p.stderr:
        return "ERROR", "the mutant no longer compiles (the code under test changed?)"
    if p.returncode == 0:
        return "SURVIVED", "every unit test still passes"
    failed = [line.split()[1] for line in p.stdout.splitlines() if line.startswith("---- ") and line.endswith(" stdout ----")]
    return "KILLED", f"failing: {', '.join(failed[:3]) or 'see cargo output'}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("group", nargs="?")
    ap.add_argument("--list", action="store_true", help="list the groups and their mutants")
    args = ap.parse_args()
    groups = json.loads((CONTRACT / "mutants.json").read_text())
    if args.list or not args.group:
        for g, ms in groups.items():
            print(f"{g}: {len(ms)} mutants")
            for m in ms:
                print(f"  {m['name']}")
        return 0
    if args.group not in groups:
        sys.exit(f"unknown group {args.group!r}; groups: {', '.join(groups)}")
    crate = copy_crate()
    # Unmutated first: a failing test would make every mutant look killed.
    p = subprocess.run(TEST, cwd=crate, capture_output=True, text=True, timeout=TIMEOUT_S,
                       env={**os.environ, "CARGO_TARGET_DIR": TARGET})
    if p.returncode != 0:
        print((p.stdout + p.stderr)[-3000:])
        sys.exit("the unit tests fail without any mutant: fix them first")
    counts = {"KILLED": 0, "SURVIVED": 0, "ERROR": 0}
    for m in groups[args.group]:
        outcome, why = check(crate, m)
        counts[outcome] += 1
        print(f"{outcome} {m['name']}: {why}", flush=True)
    print(f"mutants {args.group}: {counts['KILLED']} killed, {counts['SURVIVED']} survived, {counts['ERROR']} errors")
    return 0 if counts["KILLED"] == len(groups[args.group]) else 1


if __name__ == "__main__":
    sys.exit(main())
