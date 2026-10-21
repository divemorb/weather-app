"""The Details' stations section explains itself (REQ_DETAILS_5): what the stations
are for, each station's distance with its direction from the place, the place named
on the map, and a legend that names the map's symbols."""

from __future__ import annotations

from expect import OBS_DIRECTIONS, STATIONS_TEXT
from page import UIPage, expect_text, norm, visible_one


def stations_explained_problems(pg: UIPage) -> list[str]:
    """The intro line and the map's place label (exact texts), the legend's three
    entries, and per station row (nearest first) its direction from the place."""
    want = STATIONS_TEXT[pg.lang]
    problems = expect_text(pg, "stations-intro", want["intro"]) + expect_text(pg, "map-here", want["here"])
    legend, found = visible_one(pg, "map-legend")
    problems += found
    if legend:
        problems += [f"[data-test=map-legend] {legend['text']!r} lacks {entry!r}"
                     for entry in want["legend"] if entry not in norm(legend["text"])]
    rows = [e for e in pg.ui("observation-station") if e["visible"]]
    for e, where in zip(rows, OBS_DIRECTIONS[pg.lang]):
        if where not in norm(e["text"]):
            problems.append(f"observation station row {e['text']!r} lacks {where!r} (distance and direction)")
    return problems
