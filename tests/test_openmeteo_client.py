"""Unit tests for the Open-Meteo client (parsers + HTTP layer).

Parser tests use synthetic multi-model / ensemble payloads (no network).
HTTP-layer tests use ``httpx.MockTransport``.
"""
from __future__ import annotations

import pytest
import httpx

from app.openmeteo_client import OpenMeteoClient, parse_forecast, parse_ensemble
from app.brightsky_client import SourceError
from tests.helpers import (
    make_cfg,
    make_forecast_payload,
    make_ensemble_payload,
)


HOURS = ["2026-09-25T00:00", "2026-09-25T01:00", "2026-09-25T02:00", "2026-09-25T03:00"]
MIN15 = [
    "2026-09-25T00:00",
    "2026-09-25T00:15",
    "2026-09-25T00:30",
    "2026-09-25T00:45",
    "2026-09-25T01:00",
    "2026-09-25T01:15",
    "2026-09-25T01:30",
    "2026-09-25T01:45",
]
def _forecast_payload():
    models = ["icon_d2", "icon_eu"]
    return make_forecast_payload(

