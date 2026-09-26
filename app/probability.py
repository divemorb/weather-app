"""Pure (network-free) rain-probability logic for the next 60 minutes.

Every *decision* the aggregator makes lives here as a plain function on the
normalized dataclasses from :mod:`app.models`. No I/O, no hidden clock: the
aggregator pulls cached payloads, hands them to these functions, and
publishes the results. Keeping the logic pure is what makes it unit-testable.

Three independent signals, combined linearly (see README):

1. Radar nowcast  -> binary "is it raining within the local radius now?"
2. Model votes    -> share of models with > threshold mm in the next hour
3. Ensemble       -> share of members with > threshold mm in the next hour

    P = w_r * R + w_m * M + w_e * E        (weights renormalized to sum 1)
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

from .config import ProbabilityConfig, RadarConfig
from .models import (
    EnsembleData,
    EnsembleVote,
    ForecastBundle,
    ModelVote,
    RadarFrame,
    RadarNowcast,
)


# ---------------------------------------------------------------------------
# Geometry (radar grid is ~1 km per cell)
# ---------------------------------------------------------------------------
def _location_full_xy(nowcast: RadarNowcast) -> tuple[float, float]:
    """Location in full-grid (x, y) cell coordinates.

    The sub-grid's origin is at ``bbox`` = (top, left, bottom, right); the
    requested point is ``location_xy`` = (px, py) measured from that origin
    (fractional — the location sits inside a cell).
    """
    top, left = nowcast.bbox[0], nowcast.bbox[1]
    px, py = nowcast.location_xy
    return left + px, top + py


def cell_distance_km(nowcast: RadarNowcast, cell_x: int, cell_y: int, cell_km: float) -> float:
    """Distance (km) from the location to the radar cell (cell_x, cell_y).

    The grid is a uniform ~1 km physical grid, so the cell offset in grid
    units times the cell size is the physical offset; a plain Euclidean
    distance is accurate at this scale.
    """
    loc_x, loc_y = _location_full_xy(nowcast)
    return math.hypot((cell_x - loc_x) * cell_km, (cell_y - loc_y) * cell_km)


def radar_has_local_rain(
    nowcast: RadarNowcast,
    now: datetime,
    horizon: timedelta,
    radius_km: float,
    cell_km: float,
    cell_rain_threshold_mm: float,
) -> bool:
    """True if any cell within ``radius_km`` of the location exceeds the
    rain threshold in any frame with ``now <= frame_time < now + horizon``.
    """
    end = now + horizon
    for frame in nowcast.frames:
        if not (now <= frame.time_utc < end):
            continue
        for cell in frame.cells:
            if cell.mm <= cell_rain_threshold_mm:
                continue
            if cell_distance_km(nowcast, cell.x, cell.y, cell_km) <= radius_km:
                return True
    return False


def max_local_rain_mm(
    nowcast: RadarNowcast,
    frame: RadarFrame,
    radius_km: float,
    cell_km: float,
    threshold_mm: float,
) -> float:
    """Strongest rain (max mm) within ``radius_km`` of the location in one frame.

    Only cells whose 5-minute amount exceeds ``threshold_mm`` count (consistent
    with the radar signal's definition of "rain"), so the next-hour bar and the
    binary radar vote agree on what counts as local rain. Returns 0.0 when no
    qualifying cell lies within the radius.
    """
    best = 0.0
    for cell in frame.cells:
        if cell.mm <= threshold_mm or cell.mm <= best:
            continue
        if cell_distance_km(nowcast, cell.x, cell.y, cell_km) <= radius_km:
            best = cell.mm
    return best


# ---------------------------------------------------------------------------
# Signal 1: radar nowcast (binary vote)
# ---------------------------------------------------------------------------
def radar_rain_signal(
    nowcast: RadarNowcast | None,
    now: datetime,
    radar_cfg: RadarConfig,
    prob_cfg: ProbabilityConfig,
    horizon: timedelta = timedelta(hours=1),
) -> tuple[bool, bool | None]:
    """Return ``(radar_available, raining)``.

    ``raining`` is None when radar is unavailable or does not cover the
    location — the combined probability then falls back to models + ensemble.
    """
    if nowcast is None or not nowcast.covered or not nowcast.frames:
        return False, None
    raining = radar_has_local_rain(
        nowcast,
        now,
        horizon,
        radar_cfg.radius_km,
        radar_cfg.grid_size_km,
        prob_cfg.radar_cell_rain_threshold_mm,
    )
    return True, raining


# ---------------------------------------------------------------------------
# Signal 2: model agreement
# ---------------------------------------------------------------------------
def sum_next_hour(
    min15_time: list[datetime],
    values: list[float | None],
    now: datetime,
) -> float | None:
    """Sum of the 15-min steps starting in ``[now, now + 1 h)``.

    Returns None when no step falls in that window (stale/missing series) or
    when any involved value is missing: a model without data does not vote
    "dry", it simply does not vote.
    """
    if not min15_time:
        return None
    end = now + timedelta(hours=1)
    total = 0.0
    count = 0
    for t, v in zip(min15_time, values):
        if t < now:
            continue
        if t >= end:
            break
        if v is None:
            return None
        total += v
        count += 1
    return total if count else None


def model_votes(bundle: ForecastBundle | None, now: datetime) -> list[ModelVote]:
    """One :class:`ModelVote` per model in the bundle (bundle order)."""
    votes: list[ModelVote] = []
    for m in (bundle.models if bundle is not None else []):
        votes.append(
            ModelVote(
                name=m.name,
                precip_next_hour_mm=sum_next_hour(m.min15_time, m.min15_precip_mm, now),
            )
        )
    return votes


def model_rain_signal(
    votes: list[ModelVote], threshold_mm: float
) -> tuple[float | None, int, int]:
    """Return ``(share 0..100 | None, models_with_rain, models_total)``.

    Models whose next-hour sum is None (no data) do not count at all.
    """
    available = [v for v in votes if v.precip_next_hour_mm is not None]
    if not available:
        return None, 0, 0
    n_rain = sum(1 for v in available if v.precip_next_hour_mm > threshold_mm)
    return 100.0 * n_rain / len(available), n_rain, len(available)


# ---------------------------------------------------------------------------
# Signal 3: ensemble probability
# ---------------------------------------------------------------------------
def _hour_index_at_or_after(times: list[datetime], now: datetime) -> int | None:
    """Index of the first hourly step stamped at or after ``now`` (or None).

    Open-Meteo hourly precipitation is a *preceding-hour sum*: the value at
    time ``t`` is the rain of the hour ``[t - 1 h, t)``. So the step that
    describes the hour containing ``now`` is the first one whose timestamp is
    at or after ``now``. Returns None when ``now`` is beyond the last step
    (a stale series).
    """
    for i, t in enumerate(times):
        if t >= now:
            return i
    return None


def ensemble_vote(
    ensemble: EnsembleData | None, threshold_mm: float, now: datetime
) -> EnsembleVote:
    """Share of ensemble members with > ``threshold_mm`` in the hour that
    contains ``now``. Returns a None probability when the cached series no
    longer covers the current hour (stale) or has no usable members."""
    if ensemble is None or ensemble.n_members == 0:
        return EnsembleVote(probability_pct=None, n_members=0, n_rain_members=0)
    idx = _hour_index_at_or_after(ensemble.hourly_time, now)
    if idx is None:
        return EnsembleVote(
            probability_pct=None, n_members=ensemble.n_members, n_rain_members=0
        )
    n = 0
    n_rain = 0
    for member in ensemble.member_precip_mm:
        if idx >= len(member):
            continue
        v = member[idx]
        if v is None:
            continue
        n += 1
        if v > threshold_mm:
            n_rain += 1
    if n == 0:
        return EnsembleVote(
            probability_pct=None, n_members=ensemble.n_members, n_rain_members=0
        )
    return EnsembleVote(
        probability_pct=100.0 * n_rain / n,
        n_members=ensemble.n_members,
        n_rain_members=n_rain,
    )


# ---------------------------------------------------------------------------
# Combination
# ---------------------------------------------------------------------------
def combine_signals(
    prob_cfg: ProbabilityConfig,
    radar_available: bool,
    radar_raining: bool | None,
    model_pct: float | None,
    ensemble_pct: float | None,
) -> tuple[float, dict[str, float]]:
    """Combine the available signals into a 0..100 % probability.

    A missing signal (None) drops out and the remaining weights are
    re-normalized. Returns ``(probability_pct, weights_used)``.
    """
    signals: dict[str, float] = {}
    if radar_available and radar_raining is not None:
        signals["radar"] = 100.0 if radar_raining else 0.0
    if model_pct is not None:
        signals["models"] = model_pct
    if ensemble_pct is not None:
        signals["ensemble"] = ensemble_pct
    if not signals:
        return 0.0, {}

    base = {
        "radar": prob_cfg.weight_radar if radar_available else 0.0,
        "models": prob_cfg.weight_models,
        "ensemble": prob_cfg.weight_ensemble,
    }
    weights = {k: base[k] for k in signals}
    total = sum(weights.values())
    if total <= 0:
        # Configured weights for all available signals are zero: fall back to
        # equal weighting so the app still produces a number.
        weights = {k: 1.0 for k in signals}
        total = float(len(signals))
    weights = {k: v / total for k, v in weights.items()}

    prob = sum(weights[k] * signals[k] for k in signals)
    return max(0.0, min(100.0, prob)), weights


def build_explanation(
    radar_available: bool,
    radar_raining: bool | None,
    models_rain: int,
    models_total: int,
    ensemble_pct: float | None,
    models_threshold_mm: float,
) -> str:
    """Human-readable derivation for the UI.

    e.g. ``Radar: yes; 3 of 6 models predict > 0.1 mm in the next hour;
    ensemble 42 %``
    """
    if radar_available and radar_raining is not None:
        radar_part = "Radar: yes" if radar_raining else "Radar: no"
    else:
        radar_part = "Radar: not available"
    models_part = (
        f"{models_rain} of {models_total} models predict > "
        f"{models_threshold_mm:g} mm in the next hour"
    )
    if ensemble_pct is not None:
        ensemble_part = f"ensemble {ensemble_pct:.0f} %"
    else:
        ensemble_part = "ensemble: n/a"
    return f"{radar_part}; {models_part}; {ensemble_part}"
