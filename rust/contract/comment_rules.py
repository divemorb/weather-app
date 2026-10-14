#!/usr/bin/env python3
"""Comment rules for one area of the code (the cleanup's comment pass, 2026-10-14).

  no-history   no build-step IDs ("W2", "step F4") in comments, and no dates in app comments: git keeps history
  no-python    Rust comments don't mention Python (the Python app is retired after v2.0)
  header       the file's first comment block (module header) at most HEADER lines
  block        every other comment block at most BLOCK lines
  doc          every public Rust item, exported or top-level JS function and public
               module-level Python function has a comment right above it (Python: a docstring)

    python3 rust/contract/comment_rules.py AREA [--rule RULE ...]
    AREA: rust-app | rust-tests | page | harness

Prints one line per violation (file:line rule: detail), then a count per rule;
exits 1 on any violation.
"""
import argparse
import ast
import collections
import pathlib
import re
import sys

HEADER, BLOCK = 10, 12
REPO = pathlib.Path(__file__).resolve().parent.parent.parent
STEP_ID = re.compile(r"(?<![\w-])(?:[Ss]teps? )?(?:[ABCFGHLPRSTVW]\d{1,2}[a-z]?)(?![\w])")
DATE = re.compile(r"\b20\d\d-\d\d-\d\d\b")
RUST_TEST = re.compile(r"(^|/|_)tests?(\.rs|/)|testutil")


def area_files(area):
    if area in ("rust-app", "rust-tests"):
        files = sorted((REPO / "rust/src").rglob("*.rs"))
        tests = [p for p in files if RUST_TEST.search(str(p.relative_to(REPO / "rust/src")))]
        if area == "rust-tests":
            return tests + sorted((REPO / "rust/tests").glob("*.rs"))
        return [p for p in files if p not in tests]
    if area == "page":
        return sorted((REPO / "app/static").glob("*.js")) + sorted((REPO / "app/static").glob("*.css"))
    if area == "harness":
        u = REPO / "rust/uitest"
        return [p for p in sorted(u.glob("*.py")) + [u / "probe.js"] if p.name not in ("faults.py", "expect.py")]
    raise SystemExit(f"unknown area {area}")


def comments(path):
    """(line number, text) of every comment line; Python docstrings count."""
    text = path.read_text()
    lines = text.splitlines()
    out = []
    if path.suffix == ".py":
        doc_lines = set()
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
                d = node.body[0]
                if isinstance(d, ast.Expr) and isinstance(getattr(d, "value", None), ast.Constant) \
                        and isinstance(d.value.value, str):
                    doc_lines.update(range(d.lineno, d.end_lineno + 1))
        for i, l in enumerate(lines, 1):
            s = l.strip()
            if i in doc_lines:
                out.append((i, s.strip('"').strip("'")))
            elif "#" in l and not s.startswith(("'", '"')):
                j = l.find("#")
                if s.startswith("#") or (l[:j].count('"') % 2 == 0 and l[:j].count("'") % 2 == 0):
                    out.append((i, l[j + 1:].strip()))
        return out
    in_block = False
    for i, l in enumerate(lines, 1):
        s = l.strip()
        if in_block:
            out.append((i, s.lstrip("*").strip()))
            in_block = "*/" not in s
        elif s.startswith("//"):
            out.append((i, s.lstrip("/!").strip()))
        elif s.startswith("/*"):
            out.append((i, s[2:].lstrip("*").strip()))
            in_block = "*/" not in s[2:]
        elif "//" in s and path.suffix in (".rs", ".js") and not re.search(r"https?://", s):
            j = s.find("//")
            if s[:j].count('"') % 2 == 0 and s[:j].count("'") % 2 == 0 and s[:j].count("`") % 2 == 0:
                out.append((i, s[j + 2:].strip()))
    return out


def blocks(com):
    """Runs of consecutive comment lines: (first line, length)."""
    runs, start, prev = [], None, None
    for i, _ in com:
        if prev is None or i != prev + 1:
            if start is not None:
                runs.append((start, prev - start + 1))
            start = i
        prev = i
    if start is not None:
        runs.append((start, prev - start + 1))
    return runs


def missing_docs(path):
    lines = path.read_text().splitlines()

    def has_comment_above(i):
        j = i - 1
        while j >= 0 and lines[j].strip().startswith(("#[", "@")):
            j -= 1
        prev = lines[j].strip() if j >= 0 else ""
        return prev.startswith(("///", "//", "*", "/*")) or prev.endswith("*/")

    if path.suffix == ".rs":
        pat = re.compile(r"\s*pub(\([a-z]+\))? (async |const )?(fn|struct|enum|trait|type|const|static) ")
        return [i + 1 for i, l in enumerate(lines) if pat.match(l) and not has_comment_above(i)]
    if path.suffix == ".js":
        pat = re.compile(r"(export )?(async )?function \w+|export (const|let|class) \w+")
        return [i + 1 for i, l in enumerate(lines) if pat.match(l) and not has_comment_above(i)]
    if path.suffix == ".py":
        tree = ast.parse(path.read_text())
        return [n.lineno for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and not n.name.startswith("_") and not ast.get_docstring(n)]
    return []


def check(path, rules, area):
    rel = path.relative_to(REPO)
    dates = area in ("rust-app", "page")  # tests and harness explain their fixed fixture times
    com = comments(path)
    v = []
    if "no-history" in rules:
        for i, t in com:
            m = STEP_ID.search(t) or (dates and DATE.search(t))
            if m:
                v.append((rel, i, "no-history", m.group(0)))
    if "no-python" in rules and path.suffix == ".rs":
        v += [(rel, i, "no-python", t[:60]) for i, t in com if re.search(r"\bPython\b", t)]
    runs = blocks(com)
    first_code = next((i for i, l in enumerate(path.read_text().splitlines(), 1)
                       if l.strip() and i not in {c[0] for c in com}), 1)
    for k, (start, n) in enumerate(runs):
        is_header = k == 0 and start < first_code
        limit = HEADER if is_header else BLOCK
        rule = "header" if is_header else "block"
        if rule in rules and n > limit:
            v.append((rel, start, rule, f"{n} lines (at most {limit})"))
    if "doc" in rules:
        v += [(rel, i, "doc", "no comment above this public item") for i in missing_docs(path)]
    return v


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("area")
    ap.add_argument("--rule", nargs="*", default=["no-history", "no-python", "header", "block", "doc"])
    args = ap.parse_args()
    found = [x for p in area_files(args.area) for x in check(p, set(args.rule), args.area)]
    for rel, i, rule, detail in found:
        print(f"{rel}:{i} {rule}: {detail}")
    counts = collections.Counter(r for _, _, r, _ in found)
    print(f"comment rules ({args.area}): {len(found)} violations"
          + (" (" + ", ".join(f"{r} {n}" for r, n in counts.most_common()) + ")" if found else ""))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
