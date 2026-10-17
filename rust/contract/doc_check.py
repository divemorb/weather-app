#!/usr/bin/env python3
"""The docs point at what exists: every relative link in README.md and
docs/*.md leads to an existing file, and docs/ARCHITECTURE.md names every
file of the page (app/static: *.js, *.css, *.html) and every backend module
(rust/src/*.rs) by its file name.

Prints one line per problem and exits 1 if there is any.

    python3 rust/contract/doc_check.py
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
LINK = re.compile(r"\]\(([^)\s]+)\)")


def broken_links(doc):
    problems = []
    for target in LINK.findall(doc.read_text()):
        if re.match(r"[a-z]+:", target) or target.startswith("#"):
            continue
        path = (doc.parent / target.split("#", 1)[0]).resolve()
        if not path.exists():
            problems.append(f"{doc.relative_to(ROOT)}: link to a missing file: {target}")
    return problems


def unnamed_files(doc):
    text = doc.read_text()
    files = [p for pat in ("*.js", "*.css", "*.html") for p in (ROOT / "app/static").glob(pat)]
    files += list((ROOT / "rust/src").glob("*.rs"))
    return [f"{doc.relative_to(ROOT)}: does not name {p.relative_to(ROOT)}"
            for p in sorted(files) if not re.search(rf"(?<![\w.-]){re.escape(p.name)}(?![\w-])", text)]


def main():
    docs = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
    problems = [p for d in docs for p in broken_links(d)] + unnamed_files(ROOT / "docs/ARCHITECTURE.md")
    for p in problems:
        print(p)
    print(f"docs: {len(problems)} problems")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
