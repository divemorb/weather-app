"""A tablet turned while the big view is open: the chart is drawn at its box's
size, so after the turn it must be redrawn to fit its card again. Checked on
the rainy page, upright to lying and back."""

import time

from page_checks import CONTAINED_JS

TURNS = [(1032, 1280), (1376, 940), (1032, 1280)]  # the iPad Pro 13" in Safari, upright and lying


def kiosk_turn(run) -> list[str]:
    """The chart card's content must stay inside the card through the turns:
    upright, lying, upright again (no fixed sleep; wait for the redraw)."""
    problems: list[str] = []
    pg = run.page(width=1032, height=1280, query="?kiosk")
    try:
        for w, h in TURNS[1:]:
            pg.p.resize(w, h)
            left = pg.js(CONTAINED_JS)
            for _ in range(20):  # at most 2 s for the redraw to settle
                if not left:
                    break
                time.sleep(0.1)
                left = pg.js(CONTAINED_JS)
            for s in left:
                problems.append(f"turned to {w}x{h}: {s} reaches outside its card")
    finally:
        run.done(pg)
    return problems
