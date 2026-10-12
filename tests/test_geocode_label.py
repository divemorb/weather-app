"""Spec tests for the short place label (phone test P1, 2026-10-12).

The header showed Nominatim's whole ``display_name`` on the phone. The label
is now two lines in German order, built from ``address``
(``addressdetails=1``): "Dircksenstraße 2" / "10178 Berlin". The cases live
in ``tests/geocode_labels.json`` so the Rust tests check the same table.
"""
from __future__ import annotations

import json
import pathlib
import re

import httpx2
import pytest

from app.geocode import Geocoder, parse_nominatim

HERE = pathlib.Path(__file__).parent
CASES = json.loads((HERE / "geocode_labels.json").read_text(encoding="utf-8"))["cases"]
LIVE = HERE.parent / "rust" / "contract" / "fixtures" / "live" / "nominatim_search.json"


@pytest.mark.parametrize("case", CASES, ids=[re.sub(r"\W+", "-", c["case"]).strip("-") for c in CASES])
def test_label_from_address(case):
    entry = dict(case["entry"], lat="52.5", lon="13.4")
    assert parse_nominatim([entry]) == [
        {"label": case["label"], "latitude": 52.5, "longitude": 13.4}
    ]


def test_label_recorded_search():
    """The contract's recording (Alexanderplatz Berlin, 2026-10-12)."""
    payload = json.loads(LIVE.read_text(encoding="utf-8"))
    assert [r["label"] for r in parse_nominatim(payload)] == [
        "Alexanderplatz\nBerlin",
        "Dircksenstraße 2\n10179 Berlin",
        "Alexanderplatz\n10178 Berlin",
    ]


async def test_search_asks_for_address_details():
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json=[])

    async def no_sleep(_wait):
        return None

    g = Geocoder(
        "https://nominatim.openstreetmap.org",
        transport=httpx2.MockTransport(handler),
        clock=lambda: 1000.0,
        sleep=no_sleep,
    )
    await g.search("Dircksenstraße 2, Berlin")
    await g.aclose()
    assert requests[0].url.params["addressdetails"] == "1"
