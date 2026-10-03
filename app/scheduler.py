"""APScheduler wiring: refresh cadence for the cache.

Radar (Bright Sky): every N minutes (default 5) — never on page load.
Models (Open-Meteo): every M minutes (default 60).

The jobs are coroutines run by APScheduler's asyncio executor on the
app's event loop, so a slow upstream can't block the scheduler;
``max_instances=1`` skips a run while the previous one is still busy.
(A plain ``def`` job would run in a worker thread, with no event loop to
schedule the refresh on.) The aggregator tolerates :exc:`SourceError`
(keeps the stale cache, records the last error).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .aggregator import Aggregator
from .config import AppConfig
from .times import to_iso, utcnow

log = logging.getLogger("weather.scheduler")

#: One-off job that retries a failed models refresh (see schedule_models_retry).
MODELS_RETRY_JOB = "models_retry"

#: Scheduler job id -> cache sources that job refreshes (for the UI).
JOB_SOURCES = {
    "radar_refresh": ("radar", "current"),
    "models_refresh": ("forecast", "ensemble"),
}


def build_scheduler(cfg: AppConfig, aggregator: Aggregator) -> AsyncIOScheduler:
    """Create (do NOT start) the scheduler with both refresh jobs."""
    scheduler = AsyncIOScheduler(timezone="UTC")

    async def _radar_job() -> None:
        log.info("scheduled radar refresh")
        await _guarded(aggregator.refresh_radar, "radar")

    async def _models_job() -> None:
        log.info("scheduled models refresh")
        await _guarded(aggregator.refresh_models, "models")
        schedule_models_retry(scheduler, aggregator, cfg)

    scheduler.add_job(
        _radar_job,
        IntervalTrigger(minutes=cfg.scheduling.radar_interval_minutes),
        id="radar_refresh",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.add_job(
        _models_job,
        IntervalTrigger(minutes=cfg.scheduling.models_interval_minutes),
        id="models_refresh",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    return scheduler


def schedule_models_retry(scheduler: Any, aggregator: Any, cfg: AppConfig) -> None:
    """After a failed models refresh, try again after the radar interval
    instead of an hour later; repeats while it fails. Skipped when the
    regular run comes sooner; a new retry replaces a pending one."""
    if scheduler is None or not aggregator.models_failed():
        return
    run_at = datetime.now(timezone.utc) + timedelta(minutes=max(cfg.scheduling.radar_interval_minutes, 1))
    regular = scheduler.get_job("models_refresh")
    if regular is not None and regular.next_run_time is not None and regular.next_run_time <= run_at:
        return

    async def _retry() -> None:
        log.info("models refresh retry")
        await _guarded(aggregator.refresh_models, "models")
        schedule_models_retry(scheduler, aggregator, cfg)

    log.info("models refresh failed: retrying at %s", to_iso(run_at))
    scheduler.add_job(_retry, DateTrigger(run_date=run_at), id=MODELS_RETRY_JOB,
                      max_instances=1, replace_existing=True)


def schedule_status(scheduler: Any, cfg: AppConfig) -> dict[str, Any]:
    """Next run time per refresh job, for the UI countdown.

    ``server_time_utc`` lets the browser correct its clock offset;
    ``next_run_utc`` is None while the scheduler isn't running.
    """
    intervals = {
        "radar_refresh": cfg.scheduling.radar_interval_minutes,
        "models_refresh": cfg.scheduling.models_interval_minutes,
    }
    jobs: dict[str, Any] = {}
    for job_id, sources in JOB_SOURCES.items():
        job = scheduler.get_job(job_id) if scheduler is not None else None
        next_run = getattr(job, "next_run_time", None)
        retry = scheduler.get_job(MODELS_RETRY_JOB) if scheduler is not None and job_id == "models_refresh" else None
        retry_at = getattr(retry, "next_run_time", None)
        if retry_at is not None and (next_run is None or retry_at < next_run):
            next_run = retry_at
        jobs[job_id.removesuffix("_refresh")] = {
            "interval_minutes": intervals[job_id],
            "next_run_utc": to_iso(next_run) if next_run else None,
            "sources": list(sources),
        }
    return {"server_time_utc": to_iso(utcnow()), "jobs": jobs}


async def initial_refresh(aggregator: Aggregator) -> None:
    """Warm the cache once at startup; both refreshes run concurrently and
    tolerate source errors, so a slow upstream can't delay startup.
    """
    results = await asyncio.gather(
        _guarded(aggregator.refresh_radar, "radar"),
        _guarded(aggregator.refresh_models, "models"),
        return_exceptions=True,
    )
    for name, res in zip(("radar", "models"), results):
        if isinstance(res, Exception):
            log.warning("initial %s refresh raised: %s", name, res)


async def _guarded(coro_factory, label: str) -> None:
    """Run a refresh, logging (not raising) on unexpected errors."""
    try:
        await coro_factory()
    except Exception:
        log.exception("unhandled error in %s refresh", label)
