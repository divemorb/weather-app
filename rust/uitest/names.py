"""The UI contract's check names (what --list prints) and the scenario tables."""

from __future__ import annotations

import pathlib

import report_ui

from expect import (GLASS_SCENES, KIOSK_SIZES, LAYOUT_COLUMNS, NOW, REASON_CASES, SCENES,
                    SCENE_CASES)

HERE = pathlib.Path(__file__).resolve().parent

# --- the list of checks (also what --list prints) ---------------------------

COMMON = ["console", "requests", "lang", "location", "location-detail", "theme-light", "theme-dark", "theme-icon",
          "contrast-light", "contrast-dark", "overflow-360", "buttons", "attribution"]
GLANCE = ["rain-answer", "rain-when", "rain-probability"]
RADAR = ["radar-steps", "radar-labels", "radar-caption", "radar-dry", "radar-max"]
NOW_CHECKS = list(NOW)
CHART = ["chart-svg", "chart-series", "chart-legend", "chart-y-labels", "chart-x-labels", "chart-unit", "chart-dry"]
DETAILS = ["details-open", "details-weights", "details-signals", "details-weighting", "countdown-radar", "countdown-models",
           "countdown-page", "source-rows", "source-errors", "accuracy-table", "details-fit", "details-contrast"]
KIOSK = [f"kiosk-{w}x{h}" for w, h in KIOSK_SIZES]
KIOSK_CHART = [f"kiosk-chart-{w}x{h}" for w, h in KIOSK_SIZES]
KIOSK_FILL_CHECKS = [f"kiosk-fill-{w}x{h}" for w, h in KIOSK_SIZES]
REFRESH = ["refresh-render-error", "refresh-config-retry", "refresh-keeps-old"]
STATIONS = ["now-station", "now-fallback", "observation-stations", "station-map"]
LAYOUT = [f"layout-{w}" for w in LAYOUT_COLUMNS]
SKY = (["sky-layer"] + [f"scene-{c}" for c in SCENE_CASES] + [f"motion-{s}" for s in SCENES if s != "none"]
       + [f"still-{s}" for s in SCENES] + [f"contrast-{s}-{t}" for s in SCENES for t in ("light", "dark")]
       + [f"glass-{s}" for s in GLASS_SCENES])
REASON = [f"reason-{c}" for c in REASON_CASES]
VIEW = ["view-default", "view-toggle", "view-query", "view-phone", "view-details-only"]
BIG = ["big-labels", "big-headline", "big-hierarchy"]  # the big view (also on a phone)
KIOSK_ROOM = [f"kiosk-room-{w}x{h}" for w, h in KIOSK_SIZES]


def check_names(scenario: str, lang: str) -> list[str]:
    """The checks a scenario runs in a language, in order (what --list prints per name)."""
    if scenario in ("live", "rain"):
        names = (COMMON + GLANCE + RADAR + NOW_CHECKS + CHART + DETAILS + KIOSK + KIOSK_FILL_CHECKS + STATIONS
                 + BIG + KIOSK_ROOM)
        if scenario == "live":
            names = [n for n in names if not n.startswith("chart-") or n == "chart-dry"]
            names += REASON + ["view-label"] + (["theme-toggle"] + VIEW + ["big-tracks"] if lang == "en" else [])
        else:
            names += KIOSK_CHART + (["reduced-motion"] + REFRESH + ["rain-tracks", "reload-fires", "markup-api"]
                                    if lang == "en" else [])
            names += ["chart-single-point"]  # the one-value run as a dot (chart.py)
            names += ["dst-radar-labels", "dst-chart-x-labels"]  # the CEST->CET switch (clock.py)
        names += ["now-texts"]
        return names
    if scenario == "errors":
        return (COMMON + ["rain-answer", "rain-when", "rain-probability", "radar-unavailable", "radar-unavailable-text",
                          "now-unavailable", "chart-unavailable", "now-station", "station-map"]
                + [n for n in DETAILS if n not in ("details-weights", "details-signals")])
    if scenario == "accuracy":
        return ["console", "requests", "location", "location-detail", "rain-probability", "details-open",
                "details-weighting", "accuracy-table", "accuracy-head", "accuracy-note", "details-fit", "details-contrast",
                "overflow-360", "details-reports-none"]
    if scenario in ("report", "report-glance"):
        return report_ui.check_names(scenario, lang)
    if scenario == "fallback":
        return ["console", "now-station", "now-fallback", "fallback-text"]
    if scenario == "sky":
        return ["console", "requests"] + LAYOUT + SKY
    if scenario == "unconfigured":
        return ["console", "requests", "lang", "setup-visible", "setup-texts", "theme-light", "theme-dark",
                "theme-icon", "contrast-light", "contrast-dark", "overflow-360", "buttons"]
    if scenario == "wizard":
        return ["console", "validation", "setup-texts", "min-length", "search-failed"] if lang == "de" else \
               ["console", "requests", "validation", "setup-texts", "min-length", "search-failed", "markup-search",
                "search", "search-lines", "save", "location-long", "location-lines", "change", "cancel"]
    raise ValueError(scenario)


UI_SCENARIOS = ["live", "rain", "errors", "accuracy", "unconfigured", "wizard", "fallback", "sky", "report",
                "report-glance"]
SCENARIO_LANGS = {"wizard": ["de", "en"], "sky": ["en"], "report-glance": ["en"]}  # the German validation runs before the English save
# UI scenarios that run on another scenario's app (with faked API answers, or another static folder)
BACKEND = {"sky": "live", "report-glance": "report"}


def all_names(scenarios, langs) -> list[str]:
    """Every check name across the given scenarios and languages, plus the budget and unit checks."""
    names = ["budget", "static-files"] + [f"unit/{p.name}" for p in unit_files()]
    for sc in scenarios:
        for lang in SCENARIO_LANGS.get(sc, ["en", "de"]):
            if lang in langs:
                names += [f"{sc}/{lang}/{c}" for c in check_names(sc, lang)]
    return names


def unit_files() -> list[pathlib.Path]:
    """The unit-test .mjs files (unit/ and unit/more/)."""
    return sorted((HERE / "unit").glob("*.test.mjs")) + sorted((HERE / "unit" / "more").glob("*.test.mjs"))
