#!/usr/bin/env python3
"""Traceability: every requirement in docs/REQUIREMENTS.md names, in a
*Proof:* line under its bullet, the tests that prove it; links run one way,
requirement to tests, and never into the code. Prints one line per problem
(REQ_X: text) and exits 1 if there is any; a missing Proof line is a warning
unless --strict. --areas PROB,DATA limits that check; --report is Markdown.

    python3 rust/contract/trace.py [--strict] [--areas PROB,DATA]
    python3 rust/contract/trace.py --report | --self-test
"""
import argparse
import fnmatch
import json
import pathlib
import re
import subprocess
import sys

from trace_report import report

ROOT = pathlib.Path(__file__).resolve().parents[2]
GATES = {
    "fmt": "rust/Cargo.toml",
    "clippy": "rust/Cargo.toml",
    "sizes": "rust/contract/sizes.py",
    "comment_rules": "rust/contract/comment_rules.py",
    "doc_check": "rust/contract/doc_check.py",
    "contract": "rust/contract/run.py",
    "faults": "rust/uitest/faults.py",
    "trace": "rust/contract/trace.py",
}
TEST_KINDS = ("cargo", "contract", "ui")
MARKS = ("manual", "review", "scope", "todo")
MAX_MATCHES = 25
BULLET = re.compile(r"^- \*\*REQ_([A-Z]+)_(\d+)\*\*")
ITEM = re.compile(r"^`([a-z]+):(.*)`$")


def parse_requirements(text):
    """Requirements of a REQUIREMENTS.md text, in file order: dicts with id,
    area, items (the Proof items), refines (the Refines ids) and proof
    (whether a Proof line exists)."""
    reqs, current = [], None
    for line in text.splitlines():
        m = BULLET.match(line)
        if m:
            current = {"id": f"REQ_{m.group(1)}_{m.group(2)}", "area": m.group(1),
                       "items": [], "refines": [], "proof": False}
            reqs.append(current)
            continue
        if current is not None and line.startswith("  *Proof:*"):
            current["proof"] = True
            current["items"] = [i for i in line[10:].strip().split("; ") if i]
        elif current is not None and line.startswith("  *Refines:*"):
            current["refines"] = [t.strip() for t in line[12:].strip().split(",") if t.strip()]
        else:
            current = None
    return reqs


def classify(item, req_id, problems):
    """One Proof item as (test, kind, pattern), (gate, name), (refined,) or
    (mark, name, text); problems for anything else, then (bad,)."""
    m = ITEM.match(item)
    if m:
        kind, value = m.group(1), m.group(2)
        if kind in TEST_KINDS:
            return ("test", kind, value)
        if kind == "gate":
            return ("gate", value)
        problems.append(f"{req_id}: unknown kind {kind}")
        return ("bad",)
    if item == "refined":
        return ("refined",)
    for mark in MARKS:
        if item == mark or item.startswith(mark + ":"):
            text = item[len(mark):].lstrip(":").strip()
            if not text:
                problems.append(f"{req_id}: mark {mark} without text")
                return ("bad",)
            return ("mark", mark, text)
    problems.append(f"{req_id}: item is neither a test, refined nor a mark: {item}")
    return ("bad",)


def run_list(cmd, cwd, kind, problems):
    """The test ids of one list command; a failing command is a problem."""
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        first = ((proc.stderr or proc.stdout).splitlines() or [""])
        problems.append(f"cannot list {kind} tests: {first[0].strip()}")
        return []
    lines = [l.strip() for l in proc.stdout.splitlines() if l.strip()]
    if kind == "cargo":
        lines = [l[:-len(": test")] for l in lines if l.endswith(": test")]
    return lines


def read_lists(problems):
    """The three test lists: cargo (from rust/), contract and ui (from root)."""
    py = sys.executable
    return {
        "cargo": run_list(["cargo", "test", "--locked", "--offline", "-q", "--", "--list"],
                          ROOT / "rust", "cargo", problems),
        "contract": run_list([py, "rust/contract/run.py", "--list"], ROOT, "contract", problems),
        "ui": run_list([py, "rust/uitest/run.py", "--list"], ROOT, "ui", problems),
    }


def read_faults():
    """The planted faults of rust/uitest/faults.json (name, must_fail ids)."""
    data = json.loads((ROOT / "rust/uitest/faults.json").read_text())
    return data.get("faults", [])


def check_items(reqs, lists, problems):
    """Parsed items per requirement: (test, kind, pattern, [matches]),
    (gate, name), (refined,) or (mark, name, text); pattern and gate
    problems collected."""
    parsed = {}
    for req in reqs:
        items = []
        for item in req["items"]:
            res = classify(item, req["id"], problems)
            t = res[0]
            if t == "test":
                name, pattern = res[1], res[2]
                matches = [tst for tst in lists[name] if fnmatch.fnmatchcase(tst, pattern)]
                shown = f"`{name}:{pattern}`"
                if not matches:
                    problems.append(f"{shown} matches no test")
                elif len(matches) > MAX_MATCHES:
                    problems.append(f"{shown} matches {len(matches)} tests, at most {MAX_MATCHES}")
                items.append(("test", name, pattern, matches))
            elif t == "gate":
                name = res[1]
                if name not in GATES:
                    problems.append(f"{req['id']}: unknown gate {name}")
                elif not (ROOT / GATES[name]).is_file():
                    problems.append(f"{req['id']}: gate file missing: {GATES[name]}")
                items.append(("gate", name))
            else:
                items.append(res)
        parsed[req["id"]] = items
    return parsed


def check_refines(reqs, parsed, problems):
    """children: the requirements that refine each id; problems for Refines
    ids that are unknown, self-named or on a loop, and for refined
    requirements that no requirement refines."""
    by_id = {r["id"]: r for r in reqs}
    edges, children = {}, {r["id"]: [] for r in reqs}
    for r in reqs:
        edges[r["id"]] = []
        for ref in r["refines"]:
            if ref not in by_id:
                problems.append(f"{r['id']}: Refines unknown {ref}")
            elif ref == r["id"]:
                problems.append(f"{r['id']}: Refines itself")
            else:
                edges[r["id"]].append(ref)
                children[ref].append(r["id"])
    for r in reqs:
        if ("refined",) in parsed.get(r["id"], []) and not children[r["id"]]:
            problems.append(f"{r['id']}: refined, but no requirement refines it")
    for r in reqs:
        if on_loop(r["id"], edges):
            problems.append(f"{r['id']}: Refines loop")
    return children


def on_loop(start, edges):
    """Whether start sits on a Refines loop (can it reach itself?)."""
    seen, stack = set(), list(edges.get(start, ()))
    while stack:
        node = stack.pop()
        if node == start:
            return True
        if node not in seen:
            seen.add(node)
            stack.extend(edges.get(node, ()))
    return False


def compute_status(reqs, parsed, children):
    """Status of every requirement: automatic, todo, marked, without Proof."""
    status, busy = {}, set()

    def of(rid):
        if rid in status:
            return status[rid]
        items = parsed.get(rid, [])
        if rid in busy:  # a Refines loop, already a problem: not automatic
            return "marked"
        busy.add(rid)
        if any(i[0] in ("test", "gate") for i in items):
            s = "automatic"
        elif ("refined",) in items and children.get(rid) and \
                all(of(c) == "automatic" for c in children[rid]):
            s = "automatic"
        elif any(i[0] == "mark" and i[1] == "todo" for i in items):
            s = "todo"
        elif any(i[0] == "mark" for i in items) or ("refined",) in items:
            s = "marked"
        else:
            s = "without Proof"
        busy.discard(rid)
        status[rid] = s
        return s

    for r in reqs:
        of(r["id"])
    return status


def check_budget(counts, max_marked, max_todo, problems):
    """More marked than --max-marked, or todo than --max-todo, is a problem."""
    if counts["marked"] > max_marked:
        problems.append(f"budget: {counts['marked']} marked requirements, "
                        f"at most {max_marked} (prefer a test)")
    if counts["todo"] > max_todo:
        problems.append(f"budget: {counts['todo']} todo requirements, "
                        f"at most {max_todo} (write the missing test)")


def analyze(text, lists, faults, opts=None):
    """All problems plus the per-requirement data for the summary and report.
    opts: strict (bool), areas (tuple), max_marked (int), max_todo (int)."""
    opts = opts or {}
    strict = opts.get("strict", False)
    areas = opts.get("areas", ())
    max_marked = opts.get("max_marked", 12)
    max_todo = opts.get("max_todo", 20)
    problems = []
    reqs = parse_requirements(text)
    for rid in dict.fromkeys(r["id"] for r in reqs):
        if sum(1 for r in reqs if r["id"] == rid) > 1:
            problems.append(f"{rid}: duplicate requirement id")
    parsed = check_items(reqs, lists, problems)
    children = check_refines(reqs, parsed, problems)
    status = compute_status(reqs, parsed, children)
    area_limit = set(areas)
    missing = [r["id"] for r in reqs
               if not r["proof"] and (not area_limit or r["area"] in area_limit)]
    if strict:
        problems += [f"{rid}: no Proof line" for rid in missing]
    counts = {s: sum(1 for v in status.values() if v == s)
              for s in ("automatic", "marked", "todo", "without Proof")}
    check_budget(counts, max_marked, max_todo, problems)
    return {"reqs": reqs, "parsed": parsed, "children": children, "status": status,
            "missing": missing, "faults": faults, "problems": problems, "counts": counts}


def summary_line(data):
    """The final line: problem count and the four status counts."""
    c = data["counts"]
    return (f"trace: {len(data['problems'])} problems "
            f"({c['automatic']} automatic, {c['marked']} marked, {c['todo']} todo, "
            f"{c['without Proof']} without Proof)")


def self_test():
    """Built-in cases on small inline requirement texts and fake test lists."""
    lists = {"cargo": ["a::b::one", "a::b::two", "c::x"],
             "contract": ["report:api/x", "now:api/z"],
             "ui": ["rain/en/refresh", "rain/de/refresh", "budget"]}
    big = {"cargo": [], "contract": [], "ui": [f"t{i}" for i in range(30)]}
    faults = [{"name": "f1", "must_fail": ["rain/en/refresh"]}]

    def counts(a, m, t, w):
        return {"automatic": a, "marked": m, "todo": t, "without Proof": w}

    cases = [
        ("valid cargo id and ui pattern",
         "- **REQ_A_1** x\n  *Proof:* `cargo:a::b::one`; `ui:rain/*/refresh`\n",
         {}, lists, [], counts(1, 0, 0, 0)),
        ("pattern matches nothing",
         "- **REQ_A_1** x\n  *Proof:* `ui:foo/*`\n",
         {}, lists, ["`ui:foo/*` matches no test"], counts(1, 0, 0, 0)),
        ("pattern matches too many",
         "- **REQ_A_1** x\n  *Proof:* `ui:*`\n",
         {}, big, ["`ui:*` matches 30 tests, at most 25"], counts(1, 0, 0, 0)),
        ("unknown kind",
         "- **REQ_A_1** x\n  *Proof:* `fault:x`\n",
         {}, lists, ["REQ_A_1: unknown kind fault"], counts(0, 0, 0, 1)),
        ("unknown gate",
         "- **REQ_A_1** x\n  *Proof:* `gate:lint`\n",
         {}, lists, ["REQ_A_1: unknown gate lint"], counts(1, 0, 0, 0)),
        ("mark without text",
         "- **REQ_A_1** x\n  *Proof:* manual:\n",
         {}, lists, ["REQ_A_1: mark manual without text"], counts(0, 0, 0, 1)),
        ("refined without children",
         "- **REQ_A_1** x\n  *Proof:* refined\n",
         {}, lists, ["REQ_A_1: refined, but no requirement refines it"], counts(0, 1, 0, 0)),
        ("Refines to an unknown id",
         "- **REQ_A_1** x\n  *Proof:* `cargo:a::b::one`\n  *Refines:* REQ_Z_9\n",
         {}, lists, ["REQ_A_1: Refines unknown REQ_Z_9"], counts(1, 0, 0, 0)),
        ("Refines to itself",
         "- **REQ_A_1** x\n  *Proof:* `cargo:a::b::one`\n  *Refines:* REQ_A_1\n",
         {}, lists, ["REQ_A_1: Refines itself"], counts(1, 0, 0, 0)),
        ("Refines loop",
         "- **REQ_A_1** x\n  *Proof:* `cargo:a::b::one`\n  *Refines:* REQ_A_2\n"
         "- **REQ_A_2** y\n  *Proof:* `cargo:a::b::one`\n  *Refines:* REQ_A_1\n",
         {}, lists, ["REQ_A_1: Refines loop", "REQ_A_2: Refines loop"], counts(2, 0, 0, 0)),
        ("duplicate requirement id",
         "- **REQ_A_1** x\n  *Proof:* `cargo:a::b::one`\n"
         "- **REQ_A_1** y\n  *Proof:* `cargo:a::b::one`\n",
         {}, lists, ["REQ_A_1: duplicate requirement id"], counts(1, 0, 0, 0)),
        ("strict fails on a missing Proof line",
         "- **REQ_A_1** x\n- **REQ_B_1** y\n  *Proof:* `cargo:a::b::one`\n",
         {"strict": True}, lists, ["REQ_A_1: no Proof line"], counts(1, 0, 0, 1)),
        ("--areas limits the missing Proof line check",
         "- **REQ_A_1** x\n- **REQ_B_1** y\n  *Proof:* `cargo:a::b::one`\n",
         {"strict": True, "areas": ("B",)}, lists, [], counts(1, 0, 0, 1)),
        ("refined parent with automatic children is automatic",
         "- **REQ_A_1** p\n  *Proof:* refined\n"
         "- **REQ_A_2** c\n  *Proof:* `cargo:a::b::one`\n  *Refines:* REQ_A_1\n",
         {}, lists, [], counts(2, 0, 0, 0)),
        ("refined parent with a marked child is marked",
         "- **REQ_A_1** p\n  *Proof:* refined\n"
         "- **REQ_A_2** c\n  *Proof:* manual: do it by hand\n  *Refines:* REQ_A_1\n",
         {}, lists, [], counts(0, 2, 0, 0)),
        ("marked budget exceeded",
         "- **REQ_A_1** p\n  *Proof:* manual: one\n"
         "- **REQ_A_2** q\n  *Proof:* review: two\n",
         {"max_marked": 1}, lists,
         ["budget: 2 marked requirements, at most 1 (prefer a test)"], counts(0, 2, 0, 0)),
        ("todo item is status todo",
         "- **REQ_A_1** x\n  *Proof:* todo: a cargo test for the missing behaviour\n",
         {}, lists, [], counts(0, 0, 1, 0)),
    ]
    failed = 0
    for name, text, kw, use, want, want_counts in cases:
        data = analyze(text, use, faults, kw)
        if data["problems"] != want or data["counts"] != want_counts:
            failed += 1
            print(f"self-test case failed: {name}: problems {data['problems']}, "
                  f"counts {data['counts']}")
    print(f"self-test: {len(cases) - failed} passed")
    return 1 if failed else 0


def main():
    """Command line: check, --strict, --areas, --report or --self-test."""
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true",
                    help="a requirement without a Proof line is a problem")
    ap.add_argument("--areas", default="",
                    help="limit the no-Proof-line check to these areas (comma separated)")
    ap.add_argument("--report", action="store_true",
                    help="print the Markdown overview instead of the problem lines")
    ap.add_argument("--self-test", action="store_true", help="run the built-in cases")
    ap.add_argument("--max-marked", type=int, default=12)
    ap.add_argument("--max-todo", type=int, default=20)
    args = ap.parse_args()
    if args.self_test:
        sys.exit(self_test())
    text = (ROOT / "docs/REQUIREMENTS.md").read_text()
    areas = [a.strip().upper() for a in args.areas.split(",") if a.strip()]
    problems = []
    data = analyze(text, read_lists(problems), read_faults(),
                   {"strict": args.strict, "areas": areas,
                    "max_marked": args.max_marked, "max_todo": args.max_todo})
    problems += data["problems"]
    if args.report:
        print(report(data))
    else:
        if not args.strict:
            for rid in data["missing"]:
                print(f"warning: {rid}: no Proof line")
        for p in problems:
            print(p)
    print(summary_line(data))
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
