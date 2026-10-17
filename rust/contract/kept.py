#!/usr/bin/env python3
"""Nothing taken away from the UI suite: the checks, the planted faults and the
expected values as they were when the new-checks plan started (baseline/).

- every check in baseline/uitest_names.txt is still listed by run.py --list;
- every planted fault in baseline/faults.json is still in faults.json,
  unchanged; a gap may leave the gaps list only as a fault of the same name;
- every line of baseline/expect.py is still in expect.py (new lines may come,
  existing ones stay as they are);
- --check / --fault: names that must exist now (fnmatch patterns: a step's
  new checks, as run.py --list prints them, and its new faults).

Prints one line per problem and exits 1 if there is any.

    python3 rust/contract/kept.py [--check PATTERN ...] [--fault PATTERN ...]
"""
import argparse
import collections
import fnmatch
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
BASE = HERE / "baseline"
UITEST = HERE.parent / "uitest"


def listed_checks():
    out = subprocess.run([sys.executable, str(UITEST / "run.py"), "--list"],
                         capture_output=True, text=True, check=True).stdout
    return out.split()


def check_names(listed, wanted):
    base = (BASE / "uitest_names.txt").read_text().split()
    now = set(listed)
    problems = [f"check removed: {n}" for n in base if n not in now]
    problems += [f"no check matches {p!r}" for p in wanted if not fnmatch.filter(listed, p)]
    return problems


def check_faults(wanted):
    base = json.loads((BASE / "faults.json").read_text())
    now = json.loads((UITEST / "faults.json").read_text())
    faults = {f["name"]: f for f in now["faults"]}
    gaps = {g["name"] for g in now.get("gaps", [])}
    problems = []
    for f in base["faults"]:
        if faults.get(f["name"]) != f:
            problems.append(f"planted fault removed or changed: {f['name']}")
    for g in base.get("gaps", []):
        if g["name"] not in gaps and g["name"] not in faults:
            problems.append(f"gap removed without becoming a fault: {g['name']}")
    problems += [f"no planted fault matches {p!r}" for p in wanted if not fnmatch.filter(faults, p)]
    return problems


def check_expect():
    now = collections.Counter((UITEST / "expect.py").read_text().splitlines())
    base = collections.Counter((BASE / "expect.py").read_text().splitlines())
    return [f"expect.py: line changed or removed: {line.strip()!r}"
            for line, n in base.items() if line.strip() and now[line] < n]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", nargs="*", default=[])
    ap.add_argument("--fault", nargs="*", default=[])
    args = ap.parse_args()
    listed = listed_checks()
    problems = check_names(listed, args.check) + check_faults(args.fault) + check_expect()
    for p in problems:
        print(p)
    print(f"kept: {len(listed)} checks listed, {len(problems)} problems")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
