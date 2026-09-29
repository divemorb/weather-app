"""Scheduler wiring: jobs really run on the event loop; schedule status.

The first test drives a real :class:`AsyncIOScheduler`. The refresh jobs
used to be plain ``def`` functions calling ``asyncio.ensure_future``;
APScheduler runs those in a worker thread with no event loop, so every
scheduled refresh crashed and only the startup refresh ever ran.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.scheduler import build_scheduler, schedule_status
from app.times import parse_iso

from tests.helpers import make_cfg


class CountingAgg:
    """Records which refreshes the scheduler triggered."""

    def __init__(self):
        self.calls: list[str] = []

    async def refresh_radar(self):
        self.calls.append("radar")

    async def refresh_models(self):
        self.calls.append("models")


async def test_scheduled_jobs_run_refreshes_on_event_loop():
    agg = CountingAgg()
    scheduler = build_scheduler(make_cfg(), agg)
    scheduler.start()
    try:
        now = datetime.now(timezone.utc)
        for job_id in ("radar_refresh", "models_refresh"):
            scheduler.modify_job(job_id, next_run_time=now)
        for _ in range(100):  # up to ~2 s; normally a few ms
            if len(agg.calls) == 2:
                break
            await asyncio.sleep(0.02)
    finally:
        scheduler.shutdown(wait=False)
    assert sorted(agg.calls) == ["models", "radar"]


async def test_schedule_status_reports_next_runs():
    cfg = make_cfg()
    scheduler = build_scheduler(cfg, CountingAgg())
    scheduler.start()
    try:
        status = schedule_status(scheduler, cfg)
    finally:
        scheduler.shutdown(wait=False)
    server_now = parse_iso(status["server_time_utc"])
    radar = status["jobs"]["radar"]
    models = status["jobs"]["models"]
    assert radar["sources"] == ["radar", "current"]
    assert models["sources"] == ["forecast", "ensemble"]
    assert radar["interval_minutes"] == cfg.scheduling.radar_interval_minutes
    assert models["interval_minutes"] == cfg.scheduling.models_interval_minutes
    # first run is one interval after start (±2 s for the test itself)
    for job in (radar, models):
        delta = parse_iso(job["next_run_utc"]) - server_now
        assert abs(delta - timedelta(minutes=job["interval_minutes"])) < timedelta(seconds=2)


def test_schedule_status_without_running_scheduler():
    cfg = make_cfg()
    # not started: jobs are pending and have no next run time yet
    status = schedule_status(build_scheduler(cfg, CountingAgg()), cfg)
    assert status["jobs"]["radar"]["next_run_utc"] is None
    # no scheduler at all (e.g. API tests without the lifespan)
    status = schedule_status(None, cfg)
    assert status["jobs"]["models"]["next_run_utc"] is None
