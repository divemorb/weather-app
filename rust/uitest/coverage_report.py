#!/usr/bin/env python3
"""What of the page no check runs: JS functions and lines, CSS rules.

Run the UI suite with ``WETTER_UITEST_COVERAGE=DIR`` (see ``cdp.py``), then
``python3 rust/uitest/coverage_report.py DIR``. A line is listed when no
page ran any of its code; a rule when no page used it. A report, not a
gate: code run only by the node unit tests shows up here too.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

STATIC = pathlib.Path(__file__).resolve().parents[2] / "app" / "static"


def static_name(url: str) -> str | None:
    """The app/static file a served URL is, or None."""
    m = re.match(r"https?://[^/]+/(?:static/)?([\w.-]+\.(?:js|css))$", url)
    return m.group(1) if m and (STATIC / m.group(1)).exists() else None


def js_run_mask(text: str, functions: list[dict]) -> bytearray:
    """1 where the innermost covering block ran (outer ranges come first)."""
    ranges = [r for f in functions for r in f["ranges"]]
    ranges.sort(key=lambda r: (r["startOffset"], -r["endOffset"]))
    mask = bytearray(len(text))
    for r in ranges:  # inner ranges come later and overwrite their outer range
        val = 1 if r["count"] > 0 else 0
        mask[r["startOffset"]:r["endOffset"]] = bytes([val]) * (min(r["endOffset"], len(text)) - r["startOffset"])
    return mask


def main() -> int:
    """Merge every page's coverage in DIR and print the report."""
    snaps = [s for p in sorted(pathlib.Path(sys.argv[1]).glob("*.json")) for s in json.loads(p.read_text())]
    texts: dict[str, str] = {}
    run: dict[str, bytearray] = {}
    funcs: dict[str, dict[tuple[str, int], bool]] = {}
    css_used: dict[str, dict[tuple[int, int], bool]] = {}
    for snap in snaps:
        for script in snap["js"]:
            name = static_name(script["url"])
            if not name:
                continue
            text = texts.setdefault(name, (STATIC / name).read_text())
            mask = js_run_mask(text, script["functions"])
            acc = run.setdefault(name, bytearray(len(text)))
            for i, v in enumerate(mask):
                acc[i] |= v
            for f in script["functions"]:
                if f["functionName"]:
                    key = (f["functionName"], f["ranges"][0]["startOffset"])
                    seen = funcs.setdefault(name, {})
                    seen[key] = seen.get(key, False) or f["ranges"][0]["count"] > 0
        for rule in snap["css"]:
            name = static_name(rule["url"])
            if name:
                texts.setdefault(name, (STATIC / name).read_text())
                seen = css_used.setdefault(name, {})
                seen[(rule["start"], rule["end"])] = seen.get((rule["start"], rule["end"]), False) or rule["used"]
    line_of = lambda text, off: text.count("\n", 0, off) + 1
    print(f"coverage: {len(snaps)} page snapshots")
    unseen = sorted(p.name for p in STATIC.iterdir() if p.suffix in (".js", ".css") and p.name not in texts)
    print("files never loaded:", ", ".join(unseen) or "none")
    for name in sorted(run):
        text, acc = texts[name], run[name]
        dead_fns = sorted((line_of(text, off), fn) for (fn, off), ran in funcs.get(name, {}).items() if not ran)
        dead_lines, pos = [], 0
        for n, line in enumerate(text.split("\n"), 1):
            code = [i for i in range(pos, pos + len(line)) if not line[i - pos].isspace()]
            if code and not line.lstrip().startswith(("//", "*", "/*")) and not any(acc[i] for i in code):
                dead_lines.append(n)
            pos += len(line) + 1
        print(f"\n{name}: {len(dead_lines)} lines never run; functions never run: "
              + (", ".join(f"{fn} (l. {ln})" for ln, fn in dead_fns) or "none"))
        if dead_lines:
            print("  lines:", compact(dead_lines))
    for name in sorted(css_used):
        text = texts[name]
        unused = sorted((s, e) for (s, e), used in css_used[name].items() if not used)
        print(f"\n{name}: {len(unused)} of {len(css_used[name])} rules never used")
        for s, e in unused:
            sel = text[s:e].split("{")[0].strip().replace("\n", " ")
            print(f"  l. {line_of(text, s)}: {sel[:100]}")
    return 0


def compact(nums: list[int]) -> str:
    """1, 2, 3, 7 -> "1-3, 7"."""
    out, start = [], nums[0]
    for a, b in zip(nums, nums[1:] + [None]):
        if b != a + 1:
            out.append(f"{start}" if start == a else f"{start}-{a}")
            start = b
    return ", ".join(out)


if __name__ == "__main__":
    sys.exit(main())
