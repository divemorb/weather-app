#!/usr/bin/env python3
"""pytest with required patterns, like the contract and UI harnesses.

Every test outside the ``--pending`` files must pass. A test inside them
(spec tests written before their step) must pass only when its node id
matches a ``--require`` pattern (fnmatch); otherwise its failure is
reported, not counted. Prints ``pytest: N passed, M failed, K of them
required`` and exits 1 when a required test failed (or pytest itself broke).

    python3 rust/contract/pytest_gate.py --pending tests/test_station.py \\
        --require 'tests/test_station.py::test_now_*'
"""
from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pending", nargs="*", default=[], help="spec test files not yet required")
    ap.add_argument("--require", nargs="*", default=[], help="node-id patterns that must pass")
    args = ap.parse_args()
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-rA", "-p", "no:cacheprovider"],
                       capture_output=True, text=True)
    results = {}
    for line in r.stdout.splitlines():
        m = re.match(r"^(PASSED|FAILED|ERROR) (\S+)", line)
        if m:
            results[m.group(2)] = m.group(1)
    if not results:
        print(r.stdout[-3000:], r.stderr[-2000:])
        print("pytest: no results (collection error?)")
        return 1

    def required(node: str) -> bool:
        if node.split("::", 1)[0] not in args.pending:
            return True
        return any(fnmatch.fnmatchcase(node, p) for p in args.require)

    passed = [n for n, s in results.items() if s == "PASSED"]
    failed = [n for n, s in results.items() if s != "PASSED"]
    req_failed = [n for n in failed if required(n)]
    for n in failed:
        print(f"FAIL {n}{'' if required(n) else ' (not required yet)'}")
    if req_failed:
        tail = [l for l in r.stdout.splitlines() if l.startswith(("E ", "FAILED", "ERROR"))]
        print("\n".join(tail[:60]))
    print(f"pytest: {len(passed)} passed, {len(failed)} failed, {len(req_failed)} of them required")
    return 1 if req_failed else 0


if __name__ == "__main__":
    sys.exit(main())
