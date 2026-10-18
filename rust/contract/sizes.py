#!/usr/bin/env python3
"""Size gate: function size in the given files, and file length in the given
directories.

Function size (Python and JavaScript): no function longer than --max-lines
lines or with more than --max-args parameters. Python is measured by its AST
(first to last line of the def, decorators excluded; self/cls not counted);
JavaScript by matching braces of `function` declarations and arrow functions
with a body.

File length (--file-lines WARN MAX): walks the directory arguments for
program code (rs, py, js, mjs, css, html), skipping target/, vendor/,
node_modules/, golden/, fixtures/ and baseline/; data files (json, yaml,
lock, sql, txt) are never counted. A file over WARN lines prints a warning;
a file over MAX lines is a violation. File arguments are still checked for
function size, so both gates can run in one call.

Prints one line per violation and exits 1 if there is any (warnings don't
fail).

    python3 rust/contract/sizes.py --max-lines 80 --max-args 6 rust/uitest/*.py rust/uitest/probe.js
    python3 rust/contract/sizes.py --file-lines 400 600 rust app
    python3 rust/contract/sizes.py --file-lines 400 600 rust app --max-lines 80 rust/uitest/probe.js
"""
import argparse
import ast
import pathlib
import re
import sys

JS_FUNC = re.compile(r"(?:function\s*\*?\s*(\w*)\s*\(([^)]*)\)\s*\{)"
                     r"|(?:(\w+)\s*[:=]\s*(?:async\s*)?\(([^)]*)\)\s*=>\s*\{)"
                     r"|(?:^\s*(?:async\s+)?(\w+)\s*\(([^)]*)\)\s*\{)", re.M)

CODE_SUFFIXES = (".rs", ".py", ".js", ".mjs", ".css", ".html")
SKIP_DIRS = ("target", "vendor", "node_modules", "golden", "fixtures", "baseline")


def python_sizes(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = node.args
            names = [x.arg for x in a.posonlyargs + a.args + a.kwonlyargs]
            names = [n for n in names if n not in ("self", "cls")]
            names += [x.arg for x in (a.vararg, a.kwarg) if x]
            yield node.name, node.lineno, node.end_lineno - node.lineno + 1, len(names)


def _skip_literal(text, i):
    """Index after the string, template or comment starting at i (or i)."""
    c = text[i]
    if text.startswith("//", i):
        j = text.find("\n", i)
        return len(text) if j < 0 else j
    if text.startswith("/*", i):
        j = text.find("*/", i + 2)
        return len(text) if j < 0 else j + 2
    if c in "'\"`":
        j = i + 1
        while j < len(text) and text[j] != c:
            j += 2 if text[j] == "\\" else 1
        return j + 1
    return i


def js_sizes(path):
    text = path.read_text()
    for m in JS_FUNC.finditer(text):
        name = m.group(1) or m.group(3) or m.group(5) or "(anonymous)"
        if name in ("if", "for", "while", "switch", "catch", "with"):
            continue
        params = next(g for g in (m.group(2), m.group(4), m.group(6)) if g is not None)
        depth, i = 0, m.end() - 1
        while i < len(text):
            j = _skip_literal(text, i)
            if j != i:
                i = j
                continue
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        start = text.count("\n", 0, m.start()) + 1
        end = text.count("\n", 0, i) + 1
        args = [p for p in params.split(",") if p.strip()]
        yield name, start, end - start + 1, len(args)


def code_files(dirs):
    """Program code under dirs (by suffix), skipping build, vendored, fixture
    and data paths; data file types are never counted."""
    out = []
    for d in dirs:
        for p in sorted(d.rglob("*")):
            if not p.is_file() or p.suffix not in CODE_SUFFIXES:
                continue
            if any(part in SKIP_DIRS for part in p.relative_to(d).parts[:-1]):
                continue
            out.append(p)
    return out


def file_sizes(dirs, warn, max_lines):
    """(path, line count) of each code file over max_lines; files over warn
    lines print a warning."""
    for p in code_files(dirs):
        n = len(p.read_text().splitlines())
        if n > warn:
            print(f"WARN {p}: {n} lines (over {warn})")
        if n > max_lines:
            yield p, n


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-lines", type=int, default=80)
    ap.add_argument("--max-args", type=int, default=6)
    ap.add_argument("--file-lines", nargs=2, type=int, metavar=("WARN", "MAX"),
                    help="file length gate: warn over WARN lines, fail over MAX, in the directory arguments")
    ap.add_argument("paths", nargs="+", type=pathlib.Path)
    args = ap.parse_args()
    bad = 0
    files = 0
    func_paths = args.paths
    if args.file_lines:
        warn, max_lines = args.file_lines
        dirs = [p for p in args.paths if p.is_dir()]
        for p in args.paths:
            if not p.exists():
                print(f"{p}: no such file or directory")
                bad += 1
        files = sum(len(code_files([d])) for d in dirs)
        for p, _ in file_sizes(dirs, warn, max_lines):
            bad += 1
        func_paths = [p for p in args.paths if p.is_file()]
    for path in func_paths:
        sizes = python_sizes(path) if path.suffix == ".py" else js_sizes(path)
        for name, line, n, nargs in sizes:
            problems = ([f"{n} lines (at most {args.max_lines})"] if n > args.max_lines else []) + \
                       ([f"{nargs} arguments (at most {args.max_args})"] if nargs > args.max_args else [])
            if problems:
                bad += 1
                print(f"{path}:{line} {name}: {', '.join(problems)}")
    if args.file_lines:
        print(f"sizes: {bad} files over the limits ({files} files checked)")
    else:
        print(f"sizes: {bad} functions over the limits")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
