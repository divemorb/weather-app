"""Unit tests for the pure API-series helpers (no I/O, no network).

Covers ``build_24h_series`` (the 24 h model chart, relative to *now* and
labelled by hour start), ``build_forecast_history_rows`` (preceding-hour
labelling, only future hours stored) and ``build_radar_next_hour_bar``
(the 60-minute local-rain bar) — including the 5-minute grid alignment and
the unavailable / partial-coverage fallbacks.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import (
    ForecastBundle,
    ModelSeries,
    RadarCell,
    RadarFrame,
    RadarNowcast,
)
from app.series import (
    build_24h_series,
    build_forecast_history_rows,
    build_radar_next_hour_bar,
)

NOW = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)


def _model(
    name: str,
    hourly: list[float | None],
    start: datetime | None = None,
) -> ModelSeries:
    # the app works with tz-aware UTC datetimes everywhere
    base = (start or NOW).replace(minute=0, second=0, tzinfo=timezone.utc)
    return ModelSeries(
        name=name,
        hourly_time=[base + timedelta(hours=i) for i in range(len(hourly))],
        hourly_precip_mm=hourly,
    )


# ---------------------------------------------------------------------------
# build_24h_series
# ---------------------------------------------------------------------------
def test_24h_series_empty_bundle():
    out = build_24h_series(None, NOW, n_hours=24)
    assert out == {"hours": [], "models": [], "n_models": 0}


def test_24h_series_starts_at_now_and_labels_by_hour_start():
    # axis stamped 11:00..34:00, now = 10:20
    now = datetime(2025, 1, 1, 10, 20, tzinfo=timezone.utc)
    vals = [10.0 + i for i in range(24)]
    bundle = ForecastBundle(
        models=[
            _model("icon_d2", vals, start=datetime(2025, 1, 1, 11, 0)),
            _model("gfs", [0.0] * 24, start=datetime(2025, 1, 1, 11, 0)),
        ]
    )
    out = build_24h_series(bundle, now, n_hours=24)
    assert len(out["hours"]) == 24
    assert out["n_models"] == 2
    # first entry is the current hour (10:00), last is the 24th (next day 09:00)
    assert out["hours"][0] == "2025-01-01T10:00:00Z"
    assert out["hours"][-1] == "2025-01-02T09:00:00Z"
    by_name = {m["name"]: m["precipitation_mm"] for m in out["models"]}
    # the value plotted at 10:00 comes from the stamp at 11:00 (vals[0]):
    # the value at stamp t covers [t-1h, t)
    assert by_name["icon_d2"][0] == vals[0]
    assert by_name["icon_d2"][1] == vals[1]
    assert by_name["gfs"][0] == 0.0


def test_24h_series_excludes_stamped_now():
    # now exactly on a boundary: the stamp at 12:00 (rain of 11:00-12:00)
    # is already in the past and must not appear
    vals = [1.0, 2.0, 3.0, 4.0]
    bundle = ForecastBundle(models=[_model("icon_d2", vals)])
    out = build_24h_series(bundle, NOW, n_hours=24)
    assert out["hours"][0] == "2025-01-01T12:00:00Z"  # from stamp 13:00
    assert out["models"][0]["precipitation_mm"] == [2.0, 3.0, 4.0]


def test_24h_series_truncates_to_n_hours():
    bundle = ForecastBundle(
        models=[_model("icon_d2", [1.0, 2.0, 3.0, 4.0], start=datetime(2025, 1, 1, 12, 0))]
    )
    out = build_24h_series(bundle, NOW, n_hours=3)
    assert len(out["hours"]) == 3
    assert out["models"][0]["precipitation_mm"] == [2.0, 3.0, 4.0]


def test_24h_series_skips_misaligned_model():
    bundle = ForecastBundle(
        models=[
            _model("icon_d2", [1.0, 2.0, 3.0, 4.0], start=datetime(2025, 1, 1, 12, 0)),
            _model("gfs", [9.0, 9.0, 9.0, 9.0], start=datetime(2025, 1, 2, 12, 0)),
        ]
    )
    out = build_24h_series(bundle, NOW, n_hours=24)
    assert out["n_models"] == 1
    assert out["models"][0]["name"] == "icon_d2"


def test_24h_series_empty_when_no_future_hours():
    bundle = ForecastBundle(
        models=[_model("icon_d2", [1.0, 2.0], start=datetime(2025, 1, 1, 10, 0))]
    )
    out = build_24h_series(bundle, NOW, n_hours=24)
    assert out == {"hours": [], "models": [], "n_models": 0}


def test_24h_series_empty_when_all_models_null():
    bundle = ForecastBundle(
        models=[
            _model("icon_d2", [None] * 4, start=datetime(2025, 1, 1, 12, 0)),
            _model("gfs", [None] * 4, start=datetime(2025, 1, 1, 12, 0)),
        ]
    )
    out = build_24h_series(bundle, NOW, n_hours=24)
    assert out == {"hours": [], "models": [], "n_models": 0}


# ---------------------------------------------------------------------------
# build_forecast_history_rows
# ---------------------------------------------------------------------------
def test_history_rows_labelled_by_hour_start_and_future_only():
    # axis stamped 12:00..35:00, issued at 10:20
    issued_at = datetime(2025, 1, 1, 10, 20, tzinfo=timezone.utc)
    vals = [1.0, 2.0, 3.0, 4.0]
    bundle = ForecastBundle(
        models=[_model("icon_d2", vals, start=datetime(2025, 1, 1, 12, 0))]
    )
    rows = build_forecast_history_rows(bundle, issued_at, n_hours=24)
    assert [r["valid_from"] for r in rows] == [
        "2025-01-01T11:00:00Z",
        "2025-01-01T12:00:00Z",
        "2025-01-01T13:00:00Z",
        "2025-01-01T14:00:00Z",
    ]
    assert [r["valid_to"] for r in rows] == [
        "2025-01-01T12:00:00Z",
        "2025-01-01T13:00:00Z",
        "2025-01-01T14:00:00Z",
        "2025-01-01T15:00:00Z",
    ]
    assert [r["precip_mm"] for r in rows] == [1.0, 2.0, 3.0, 4.0]
    for r in rows:
        # each row covers exactly one hour and has not started yet
        vf = datetime.fromisoformat(r["valid_from"].replace("Z", "+00:00"))
        vt = datetime.fromisoformat(r["valid_to"].replace("Z", "+00:00"))
        assert vt - vf == timedelta(hours=1)
        assert vf >= issued_at
        assert r["issued_at"] == "2025-01-01T10:20:00Z"


def test_history_rows_skip_past_hours():
    # issued exactly on an hour boundary: the hour ending at 12:00
    # (11:00-12:00, stamp 12:00) has just finished -> not stored
    vals = [1.0, 2.0, 3.0]
    bundle = ForecastBundle(models=[_model("icon_d2", vals)])
    rows = build_forecast_history_rows(bundle, NOW, n_hours=24)
    # stamp 12:00 covers [11:00, 12:00) -> valid_from 11:00 < 12:00 -> dropped
    assert [r["valid_from"] for r in rows] == [
        "2025-01-01T12:00:00Z",
        "2025-01-01T13:00:00Z",
    ]


def test_history_rows_keep_24_future_hours_when_issued_late():
    # 3-day axis, issued at 10:20: 24 future hours span two calendar days
    issued_at = datetime(2025, 1, 1, 10, 20, tzinfo=timezone.utc)
    bundle = ForecastBundle(
        models=[
            _model(
                "icon_d2",
                [0.1] * 72,
                start=datetime(2025, 1, 1, 12, 0),
            )
        ]
    )
    rows = build_forecast_history_rows(bundle, issued_at, n_hours=24)
    assert len(rows) == 24
    assert rows[0]["valid_from"] == "2025-01-01T11:00:00Z"
    assert rows[-1]["valid_from"] == "2025-01-02T10:00:00Z"
    assert all(r["valid_from"] >= "2025-01-01T10:20:00Z" for r in rows)


def test_history_rows_skip_null_precipitation():
    bundle = ForecastBundle(
        models=[_model("icon_d2", [None, 2.0, None], start=datetime(2025, 1, 1, 12, 0))]
    )
    rows = build_forecast_history_rows(bundle, NOW, n_hours=24)
    assert [r["precip_mm"] for r in rows] == [2.0]


def test_history_rows_skip_model_with_null_data():
    bundle = ForecastBundle(
        models=[
            # axis 12:00..14:00: the hour ending at 12:00 is past at NOW
            _model("icon_d2", [1.0, 2.0, 3.0], start=datetime(2025, 1, 1, 12, 0)),
            _model("gfs", [None, None, None], start=datetime(2025, 1, 1, 12, 0)),
        ]
    )
    rows = build_forecast_history_rows(bundle, NOW, n_hours=24)
    assert {r["model"] for r in rows} == {"icon_d2"}
    assert [r["precip_mm"] for r in rows] == [2.0, 3.0]


# ---------------------------------------------------------------------------
# build_radar_next_hour_bar
# ---------------------------------------------------------------------------
def _cell(x: int, y: int, mm: float) -> RadarCell:
    return RadarCell(x=x, y=y, mm=mm)


def _frame(offset_min: int, cells: list[RadarCell]) -> RadarFrame:
    return RadarFrame(
        time_utc=NOW + timedelta(minutes=offset_min),
        cells=cells,
        max_mm=max((c.mm for c in cells), default=0.0),
    )


def _nowcast(frames, covered: bool = True) -> RadarNowcast:
    return RadarNowcast(frames=frames, covered=covered, bbox=(0, 0, 10, 10), location_xy=(5.0, 5.0))


def test_bar_none_nowcast_is_unavailable():
    out = build_radar_next_hour_bar(None, NOW, 5.0, 1.0, 0.05)
    assert out["available"] is False
    assert len(out["steps"]) == 12
    assert all(s["precip_mm"] == 0.0 for s in out["steps"])


def test_bar_not_covered_is_unavailable():
    out = build_radar_next_hour_bar(
        _nowcast([_frame(0, [_cell(5, 5, 0.3)])], covered=False), NOW, 5.0, 1.0, 0.05
    )
    assert out["available"] is False


def test_bar_matches_frames_on_grid():
    # frames at +0, +5, +10 min; rain only in the +5 bucket at the location
    nc = _nowcast(
        [
            _frame(0, []),
            _frame(5, [_cell(5, 5, 0.3)]),
            _frame(10, []),
        ]
    )
    out = build_radar_next_hour_bar(nc, NOW, 5.0, 1.0, 0.05)
    assert out["available"] is True
    steps = out["steps"]
    assert steps[0]["start_utc"] == "2025-01-01T12:00:00Z"
    assert steps[0]["precip_mm"] == 0.0
    assert steps[1]["start_utc"] == "2025-01-01T12:05:00Z"
    assert steps[1]["precip_mm"] == 0.3
    assert steps[2]["precip_mm"] == 0.0
    # the remaining 9 buckets have no radar frame yet -> dry
    assert all(s["precip_mm"] == 0.0 for s in steps[3:])


def test_bar_ignores_cells_outside_radius():
    # 0.5 mm 15 km away (outside the 5 km radius) must not show in the bar
    nc = _nowcast([_frame(0, [_cell(5, 5, 0.1), _cell(20, 5, 0.5)])])
    out = build_radar_next_hour_bar(nc, NOW, 5.0, 1.0, 0.05)
    assert out["steps"][0]["precip_mm"] == 0.1  # only the local cell


def test_bar_ignores_below_threshold():
    # 0.04 mm at the location is below the 0.05 mm threshold -> not rain
    nc = _nowcast([_frame(0, [_cell(5, 5, 0.04)])])
    out = build_radar_next_hour_bar(nc, NOW, 5.0, 1.0, 0.05)
    assert out["steps"][0]["precip_mm"] == 0.0


def test_bar_floors_now_to_grid():
    # now = 12:03 -> floored to 12:00; a frame at 12:00 lands in bucket 0
    now = NOW + timedelta(minutes=3)
    nc = _nowcast([_frame(0, [_cell(5, 5, 0.2)])])  # frame at 12:00
    out = build_radar_next_hour_bar(nc, now, 5.0, 1.0, 0.05)
    assert out["steps"][0]["start_utc"] == "2025-01-01T12:00:00Z"
    assert out["steps"][0]["precip_mm"] == 0.2


def test_bar_custom_step_count():
    nc = _nowcast([_frame(0, [_cell(5, 5, 0.2)])])
    out = build_radar_next_hour_bar(nc, NOW, 5.0, 1.0, 0.05, n_steps=4)
    assert len(out["steps"]) == 4
    assert out["steps"][0]["precip_mm"] == 0.2
    assert all(s["precip_mm"] == 0.0 for s in out["steps"][1:])
