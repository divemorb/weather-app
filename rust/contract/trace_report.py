#!/usr/bin/env python3
"""The Markdown overview for trace.py --report: gaps, the non-automatic
requirements, the Refines edges and one table per area.

    python3 rust/contract/trace.py --report
"""
import fnmatch


def tests_of(items, kind):
    """The (kind, matches) test items of a requirement's parsed items."""
    return [i for i in items if i[0] == "test" and i[1] == kind]


def faults_of(items, faults):
    """The planted faults that prove a requirement: one of the fault's
    must_fail ids matches one of the requirement's ui patterns."""
    ui = [i[2] for i in items if i[0] == "test" and i[1] == "ui"]
    if not ui:
        return []
    return [f["name"] for f in faults
            if any(fnmatch.fnmatchcase(m, p) for m in f.get("must_fail", []) for p in ui)]


def marks_of(items):
    """The mark items of a requirement's parsed items."""
    return [f"{i[1]}: {i[2]}" for i in items if i[0] == "mark"]


def kinds_cell(items, kind, max_ids=6):
    """A table cell: the test count of one kind plus up to max_ids ids."""
    matches = [m for i in tests_of(items, kind) for m in i[3]]
    shown = ", ".join(f"`{m}`" for m in matches[:max_ids])
    extra = f" (+{len(matches) - max_ids})" if len(matches) > max_ids else ""
    if not matches:
        return ""
    return f"{len(matches)}: {shown}{extra}"


def gap_section(data):
    """## Gaps (todo): each requirement with its todo text."""
    lines = ["## Gaps (todo)", ""]
    for r in data["reqs"]:
        todos = [f"{i[1]}: {i[2]}" for i in data["parsed"].get(r["id"], [])
                 if i[0] == "mark" and i[1] == "todo"]
        lines += [f"- **{r['id']}** {t}" for t in todos]
    if len(lines) == 2:
        lines.append("(none)")
    return lines + [""]


def not_automatic_section(data):
    """## Not automatic: each marked requirement with its marks."""
    lines = ["## Not automatic", ""]
    for r in data["reqs"]:
        if data["status"].get(r["id"]) != "marked":
            continue
        items = data["parsed"].get(r["id"], [])
        marks = marks_of(items)
        if ("refined",) in items:
            slow = [c for c in data["children"].get(r["id"], [])
                    if data["status"].get(c) != "automatic"]
            marks += [f"refined, not automatic child: {', '.join(slow)}"]
        lines.append(f"- **{r['id']}** {('; '.join(marks)) if marks else '(no mark)'}")
    if len(lines) == 2:
        lines.append("(none)")
    return lines + [""]


def refines_section(data):
    """## Refines: each parent with its children."""
    lines = ["## Refines", ""]
    for r in data["reqs"]:
        if data["children"].get(r["id"]):
            lines.append(f"- **{r['id']}** {', '.join(data['children'][r['id']])}")
    if len(lines) == 2:
        lines.append("(none)")
    return lines + [""]


def by_area_section(data):
    """## By area: one table per area, in the order the areas appear."""
    lines = ["## By area", ""]
    seen, areas = set(), []
    for r in data["reqs"]:
        if r["area"] not in seen:
            seen.add(r["area"])
            areas.append(r["area"])
    for area in areas:
        lines += [f"### {area}", "",
                  "| Requirement | cargo | contract | ui | Faults | Marks |",
                  "|---|---|---|---|---|---|"]
        for r in data["reqs"]:
            if r["area"] != area:
                continue
            items = data["parsed"].get(r["id"], [])
            cells = [f"**{r['id']}**"]
            cells += [kinds_cell(items, k) for k in ("cargo", "contract", "ui")]
            cells += ["; ".join(faults_of(items, data["faults"])),
                      "; ".join(marks_of(items))]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    return lines


def report(data):
    """The whole Markdown report of an analyze() result."""
    c = data["counts"]
    head = [f"# Traceability", "",
            f"{len(data['reqs'])} requirements: {c['automatic']} automatic, "
            f"{c['marked']} marked, {c['todo']} todo, {c['without Proof']} without Proof.",
            f"{len(data['problems'])} problems.", ""]
    return "\n".join(head + gap_section(data) + not_automatic_section(data)
                     + refines_section(data) + by_area_section(data))
