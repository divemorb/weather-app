"""Pure (network-free) rain-probability logic for the next 60 minutes.

This module contains every *decision* the aggregator makes, as plain
functions on the normalized dataclasses from ``app.models``. Keeping them
pure and free of I/O is what makes them unit-testable: the aggregator's job
is only to pull cached payloads, hand them to these functions, and publish
the results.

Three independent signals, combined linearly (see README):

1. Radar nowcast  -> binary "is it raining within the local radius now?"
2. Model votes    -> share of models with > threshold mm in the next hour
3. Ensemble       -> share of members with > threshold mm in the next hour

    P = w_r * R + w_m * M + w_e * E        (weights renormalized to sum 1)
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Sequence

from .config import ProbabilityConfig, RadarConfig
from .models import (
    EnsembleData,
    EnsembleVote,
    ForecastBundle,
    Model24hSeries,
    ModelSeries,
    ModelVote,
    RadarCell,
    RadarNowcast,
)
from .times import to_iso

#: WGS-84 mean Earth radius (km) for the haversine distance.
_EARTH_RADIUS_KM = 6371.0


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS-84 points, in kilometres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * _EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def cell_distance_km(
    lat: float,
    lon: float,
    lat0: float,
    lon0: float,
    dx: int,
    dy: int,
    cell_km: float,
) -> float:
    """Distance (km) between two points on the ~1 km radar grid.

    ``dx``/``dy`` are integer cell offsets from the reference point
    (``lat0``, ``lon0``). The offset is converted to degrees (1 degree
    latitude = 111.19 km; 1 degree longitude = 111.19 * cos(lat) km) and a
    plain Euclidean distance is used — fine at km scale.
    """
    dlat = dy * cell_km / 111.19
    dlon = dx * cell_km / (111.19 * math.cos(math.radians(lat0)))
    return math.hypot(dlat, dlon)


def cells_within_radius(
    frame: "RadarFrame",
    lat: float,
    lon: float,
    radius_km: float,
    cell_km: float,
) -> list[RadarCell]:
    """Cells of one radar frame within ``radius_km`` of the location."""
    from .models import RadarFrame  # noqa: F401  (type hint only)

    top, left, _, _ = frame_bbox
    return []
