"""The text checks the page checks leave out: the Now card's title and dt
labels (no data-test on the labels), the radar's not-available line, the
fallback note's wording, and the setup form's save button."""

from __future__ import annotations

from expect import NOW_FALLBACK, NOW_FALLBACK_NAME, NOW_LABELS, NOW_TITLE, RADAR_UNAVAILABLE, SETUP_SAVE
from page import UIPage, expect_text, norm


def now_texts_problems(pg: UIPage, lang: str) -> list[str]:
    """The Now card's title and its dt labels, word for word (the values are
    checked by the now-* checks)."""
    problems = []
    title = pg.js("document.getElementById('now-title')?.textContent || ''")
    if norm(title) != norm(NOW_TITLE[lang]):
        problems.append(f"#now-title shows {norm(title)!r}, expected {NOW_TITLE[lang]!r}")
    labels = pg.js("[...document.querySelectorAll('.now-grid dt')].map((d) => d.textContent)")
    want = [norm(x) for x in NOW_LABELS[lang]]
    if len(labels) != len(want):
        return problems + [f"{len(labels)} labels in .now-grid, expected {len(want)}: {labels}"]
    for i, (got, w) in enumerate(zip(labels, want)):
        if norm(got) != w:
            problems.append(f".now-grid label {i + 1} shows {norm(got)!r}, expected {w!r}")
    return problems


def radar_unavailable_text_problems(pg: UIPage, lang: str) -> list[str]:
    """The radar card's 'not available' line, word for word (its visibility is
    checked by the radar-unavailable check)."""
    return expect_text(pg, "radar-unavailable", RADAR_UNAVAILABLE[lang])


def fallback_text_problems(pg: UIPage, lang: str) -> list[str]:
    """The fallback note on the cloud cover value: the wording with the
    station's name (the mark's presence is checked by the now-fallback check)."""
    marks = [e for e in pg.ui("now-fallback") if e["visible"]]
    if len(marks) != 1:
        return [f"{len(marks)} visible [data-test=now-fallback], expected 1"]
    want = NOW_FALLBACK[lang].replace("{name}", NOW_FALLBACK_NAME)
    return ([f"[data-test=now-fallback] shows {norm(marks[0]['text'])!r}, expected {want!r}"]
            if norm(marks[0]["text"]) != norm(want) else [])


def setup_texts_problems(pg: UIPage, lang: str) -> list[str]:
    """The setup form's save button, word for word (the form's presence is
    checked by the setup-visible check)."""
    return expect_text(pg, "setup-save", SETUP_SAVE[lang])
