"""Unit tests for the ensemble vote (pure logic, no I/O, no network).

Split out of ``test_probability.py`` (step 6h): the ``_ensemble`` helper and
the ``test_ensemble_vote_*`` tests. No behavior change.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import EnsembleData
from app.probability import ensemble_vote

NOW = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)


def _ensemble(members: list[list[float | None]]) -> EnsembleData:
    hours = [NOW.replace(minute=0, second=0) + timedelta(hours=i) for i in range(4)]
    return EnsembleData(hourly_time=hours, member_precip_mm=members)


def test_ensemble_vote_share():
    # now = 11:30 -> the next hour is [11:30, 12:30); the first step stamped
    # after now is idx0 (stamped 12:00, covering 11:00-12:00, the next hour).
    data = _ensemble(
        [
            [1.0, 0, 0, 0],  # rain at idx0
            [0.0, 0, 0, 0],  # dry at idx0
            [0.05, 0, 0, 0],  # below threshold (0.1)
            [3.0, 0, 0, 0],  # rain at idx0
        ]
    )
    vote = ensemble_vote(data, 0.1, NOW - timedelta(minutes=30))
    assert vote.n_members == 4
    assert vote.n_rain_members == 2
    assert vote.probability_pct == pytest.approx(50.0)


def test_ensemble_vote_now_exactly_on_boundary_selects_next_index():
    # steps are stamped 12:00, 13:00, ...; at now = 12:00 exactly, idx0
    # (stamped 12:00) covers 11:00-12:00 and is the past, so idx1 (stamped
    # 13:00, covering 12:00-13:00) must be selected.
    data = _ensemble(
        [
            [0.0, 5.0, 0, 0],  # dry at idx0 (past), rain at idx1 (next hour)
            [0.0, 5.0, 0, 0],
        ]
    )
    vote = ensemble_vote(data, 0.1, NOW)
    assert vote.n_rain_members == 2
    assert vote.probability_pct == pytest.approx(100.0)


def test_ensemble_vote_uses_current_hour():
    # now = 12:30 -> the next hour is [12:30, 13:30); the first step stamped
    # after now is idx1 (stamped 13:00, covering 12:00-13:00).
    now = NOW + timedelta(minutes=30)
    data = _ensemble(
        [
            [0.0, 5.0, 0, 0],  # dry at idx0, rain at idx1
            [0.0, 0.0, 0, 0],  # dry at idx1
        ]
    )
    vote = ensemble_vote(data, 0.1, now)
    assert vote.n_rain_members == 1
    assert vote.probability_pct == pytest.approx(50.0)


def test_ensemble_vote_stale_is_none():
    # now beyond the series (all hours in the past)
    now = NOW + timedelta(hours=5)
    data = _ensemble([[1.0, 0, 0, 0], [1.0, 0, 0, 0]])
    vote = ensemble_vote(data, 0.1, now)
    assert vote.probability_pct is None


def test_ensemble_vote_none_inputs():
    assert ensemble_vote(None, 0.1, NOW).probability_pct is None
    assert ensemble_vote(EnsembleData(), 0.1, NOW).probability_pct is None


def test_ensemble_vote_skips_null_members():
    # now = 11:30 -> idx0 (stamped 12:00) is the next hour
    data = _ensemble([[1.0, 0, 0, 0], [None, 0, 0, 0]])
    vote = ensemble_vote(data, 0.1, NOW - timedelta(minutes=30))
    # only member 0 is usable; it rains -> 100%
    assert vote.n_rain_members == 1
    assert vote.probability_pct == pytest.approx(100.0)
