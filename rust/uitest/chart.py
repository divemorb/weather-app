"""The 24-hour chart's one-value edge: a run of one number between gaps is
drawn as a dot (chart.js, ``cur.length === 1``). No scenario's real data has
such a run, so the check fakes /api/models/24h (the real answer's hours and a
model name, one value, the rest null)."""

from __future__ import annotations

import json
import urllib.request

from page import Run, visible_one


def chart_single_point(run: Run) -> list[str]:
    """One model, one non-null hour: the series must draw a visible dot and
    no line. The fake keeps the app's real hours and the first model's name,
    so only the precipitation values differ from the rain page's real data."""
    with urllib.request.urlopen(run.base + "/api/models/24h", timeout=10) as r:
        real = json.loads(r.read() or "null")
    hours = (real or {}).get("hours") or []
    models = (real or {}).get("models") or []
    if len(hours) != 24 or not models:
        return [f"the app's /api/models/24h has {len(hours)} hours and {len(models)} models, "
                "expected 24 and at least one"]
    name = models[0]["name"]
    vals = [None] * len(hours)
    vals[len(vals) // 2] = 1.2
    body = {"available": True, "hours": hours,
            "models": [{"name": name, "precipitation_mm": vals}], "n_models": 1}
    pg = run.page(fakes={"/api/models/24h": [(200, json.dumps(body))]})
    try:
        svg, problems = visible_one(pg, "chart")
        if not svg:
            return problems or ["no visible [data-test=chart]"]
        info = pg.js(f"""(() => {{
          const g = document.querySelector('[data-test="chart-series"][data-model="{name}"]');
          if (!g) return {{missing: true}};
          const ok = (e) => e.checkVisibility({{checkOpacity: true, checkVisibilityCSS: true}});
          const circles = [...g.querySelectorAll("circle")].filter(ok);
          return {{circles: circles.length, paths: g.querySelectorAll("path").length,
                  r: circles[0] && circles[0].getAttribute("r")}};
        }})()""")
        return problems + _dot_problems(info, name)
    finally:
        run.done(pg)


def _dot_problems(info, name: str) -> list[str]:
    """The problems for the dot: exactly one visible circle in the series, no
    line (a single value is a dot, not a line)."""
    if info is None or info.get("missing"):
        return [f"no [data-test=chart-series] for {name}: the one model must still be drawn"]
    problems = []
    if info["circles"] != 1:
        problems.append(f"{info['circles']} circles in {name}'s series, expected 1 "
                        "(a run of one value between gaps is drawn as a dot)")
    elif info.get("r") is None or float(info["r"]) < 1:
        problems.append(f"the dot's radius is {info.get('r')}: it must be visible")
    if info["paths"]:
        problems.append(f"{info['paths']} lines in {name}'s series: one value is a dot, not a line")
    return problems
