#!/usr/bin/env python3
"""Check that code files differ from a recorded state in comments only.

``--write KEYS`` records a hash per code file under ROOTS; ``--check KEYS``
fails on any code file whose hash changed, appeared or disappeared (no git
needed, so it runs in the watchdog's sandbox). Python is
compared as its AST without docstrings; Rust, JS and CSS as their token text
with comments removed (string, char and template literals kept verbatim,
whitespace outside them ignored); HTML without ``<!-- -->`` comments;
Markdown and other text are not compared (prose is reviewed). A new or
deleted code file is a change. Prints one line per file and exits 1 on any
code change.

    python3 rust/contract/comments_only.py --write rust/contract/code_keys.json
    python3 rust/contract/comments_only.py --check rust/contract/code_keys.json
"""
from __future__ import annotations

import ast
import hashlib
import json
import pathlib
import re
import subprocess
import sys


def strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                node.body = body[1:] or [ast.Pass()]
    return tree


def py_key(src: str) -> str:
    return ast.dump(strip_docstrings(ast.parse(src)), include_attributes=False)


def c_like_key(src: str, lang: str) -> str:
    """Token text without comments: literals verbatim, other whitespace collapsed."""
    out, i, n = [], 0, len(src)
    while i < n:
        c, nxt = src[i], src[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/" and lang != "css":
            j = src.find("\n", i)
            i = n if j < 0 else j
            out.append(" ")
        elif c == "/" and nxt == "*":
            depth, i = 1, i + 2
            while i < n and depth:
                if src.startswith("/*", i) and lang == "rs":
                    depth, i = depth + 1, i + 2
                elif src.startswith("*/", i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            out.append(" ")
        elif lang == "rs" and re.match(r'b?r(#*)"', src[i:i + 300]):
            m = re.match(r'b?r(#*)"', src[i:])
            end = src.find('"' + m.group(1), i + m.end())
            end = n if end < 0 else end + 1 + len(m.group(1))
            out.append(src[i:end]); i = end
        elif c in "\"'`" and not (lang == "rs" and c == "'" and re.match(r"'[A-Za-z_]\w*(?!')", src[i:i + 64])):
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            out.append(src[i:j + 1]); i = j + 1
        elif c.isspace():
            out.append(" "); i += 1
        else:
            out.append(c); i += 1
    return re.sub(r" +", " ", "".join(out)).strip()


def html_key(src: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<!--.*?-->", " ", src, flags=re.S)).strip()


def key(path: str, src: str) -> str | None:
    ext = path.rsplit(".", 1)[-1]
    if ext == "py":
        return py_key(src)
    if ext in ("rs", "js", "mjs", "css"):
        return c_like_key(src, {"mjs": "js"}.get(ext, ext))
    if ext == "html":
        return html_key(src)
    return None


ROOTS = ["app", "tests", "rust/src", "rust/tests", "rust/uitest", "rust/contract"]
CODE = {"py", "rs", "js", "mjs", "css", "html"}


def code_files() -> list[str]:
    out = []
    for root in ROOTS:
        for p in pathlib.Path(root).rglob("*"):
            if p.is_file() and p.suffix[1:] in CODE and "__pycache__" not in p.parts:
                out.append(str(p))
    return sorted(out)


def file_key(path: str) -> str:
    return hashlib.sha256(key(path, pathlib.Path(path).read_text(encoding="utf-8")).encode()).hexdigest()


def main() -> int:
    mode, keys_path = sys.argv[1], sys.argv[2]
    if mode == "--write":
        keys = {f: file_key(f) for f in code_files()}
        pathlib.Path(keys_path).write_text(json.dumps(keys, indent=0, sort_keys=True) + "\n")
        print(f"comments-only: recorded {len(keys)} code files")
        return 0
    want = json.loads(pathlib.Path(keys_path).read_text())
    have = code_files()
    bad = [f"CODE {f}: new file" for f in have if f not in want]
    bad += [f"CODE {f}: deleted" for f in want if f not in have]
    for f in have:
        if f in want:
            try:
                if file_key(f) != want[f]:
                    bad.append(f"CODE {f}: code changed, not only comments")
            except SyntaxError as e:
                bad.append(f"CODE {f}: does not parse ({e})")
    print("\n".join(bad))
    print(f"comments-only: {len(have)} code files, {len(bad)} with code changes")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
