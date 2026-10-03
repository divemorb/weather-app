"""Scheduler wiring: jobs really run on the event loop; schedule status.

The first test drives a real :class:`AsyncIOScheduler`: APScheduler runs
plain ``def`` jobs in a worker thread with no event loop.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.scheduler import MODELS_RETRY_JOB, build_scheduler, schedule_models_retry, schedule_status
from app.times import parse_iso

from tests.aggregator_support import make_aggregator, make_payloads
from tests.aggregator_support import make_cfg as make_cfg_agg
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


# A models refresh that fails is retried after the radar interval, not an hour later.
class ModelsAgg(CountingAgg):
    def __init__(self, failed: bool):
        super().__init__()
        self.failed = failed

    def models_failed(self) -> bool:
        return self.failed


def _models_next(scheduler, cfg) -> timedelta:
    status = schedule_status(scheduler, cfg)
    return parse_iso(status["jobs"]["models"]["next_run_utc"]) - parse_iso(status["server_time_utc"])


async def _run_retry_now(scheduler, agg, calls: int) -> None:
    scheduler.modify_job(MODELS_RETRY_JOB, next_run_time=datetime.now(timezone.utc))
    for _ in range(100):  # up to ~2 s; normally a few ms
        if len(agg.calls) >= calls:
            break
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.05)  # the retry job schedules its follow-up after the refresh


async def test_failed_models_refresh_is_retried_after_the_radar_interval():
    cfg = make_cfg()
    agg = ModelsAgg(failed=True)
    scheduler = build_scheduler(cfg, agg)
    scheduler.start()
    try:
        schedule_models_retry(scheduler, agg, cfg)
        retry = timedelta(minutes=cfg.scheduling.radar_interval_minutes)
        assert abs(_models_next(scheduler, cfg) - retry) < timedelta(seconds=2)
    finally:
        scheduler.shutdown(wait=False)


async def test_no_retry_after_a_good_refresh_or_when_the_regular_run_is_sooner():
    cfg = make_cfg()
    agg = ModelsAgg(failed=False)
    scheduler = build_scheduler(cfg, agg)
    scheduler.start()
    try:
        schedule_models_retry(scheduler, agg, cfg)
        assert scheduler.get_job(MODELS_RETRY_JOB) is None
        agg.failed = True
        scheduler.modify_job("models_refresh", next_run_time=datetime.now(timezone.utc) + timedelta(minutes=1))
        schedule_models_retry(scheduler, agg, cfg)
        assert scheduler.get_job(MODELS_RETRY_JOB) is None
    finally:
        scheduler.shutdown(wait=False)


async def test_retry_repeats_while_failing_and_stops_after_success():
    cfg = make_cfg()
    agg = ModelsAgg(failed=True)
    scheduler = build_scheduler(cfg, agg)
    scheduler.start()
    try:
        schedule_models_retry(scheduler, agg, cfg)
        await _run_retry_now(scheduler, agg, 1)
        assert agg.calls == ["models"]
        assert scheduler.get_job(MODELS_RETRY_JOB) is not None  # still failing: next retry
        agg.failed = False
        await _run_retry_now(scheduler, agg, 2)
        assert agg.calls == ["models", "models"]
        assert scheduler.get_job(MODELS_RETRY_JOB) is None
        assert _models_next(scheduler, cfg) > timedelta(minutes=30)  # back to the hourly run
    finally:
        scheduler.shutdown(wait=False)


async def test_aggregator_reports_a_failed_models_refresh(store):
    payloads = make_payloads()
    failing = make_aggregator(make_cfg_agg(), store, payloads, payloads, errors=("ensemble",))
    await failing.refresh_models()
    assert failing.models_failed()
    working = make_aggregator(make_cfg_agg(), store, payloads, payloads)
    await working.refresh_models()
    assert not working.models_failed()
