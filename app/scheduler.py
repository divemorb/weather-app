"""APScheduler wiring: refresh cadence for the cache.

Radar (Bright Sky): every N minutes (default 5) — never on page load.
Models (Open-Meteo): every M minutes (default 60).

Each job runs the corresponding aggregator refresh as a task so a slow or
failing upstream can't block the scheduler; the aggregator itself tolerates
:exc:`SourceError` (keeps the stale cache, records the last error).
"""
from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .aggregator import Aggregator
from .config import AppConfig

log = logging.getLogger("weather.scheduler")


def build_scheduler(cfg: AppConfig, aggregator: Aggregator) -> AsyncIOScheduler:
    """Create (do NOT start) the scheduler with both refresh jobs."""
    scheduler = AsyncIOScheduler(timezone="UTC")

    def _radar_job() -> None:
        log.info("scheduled radar refresh")
        asyncio.ensure_future(_guarded(aggregator.refresh_radar, "radar"))

    def _models_job() -> None:
        log.info("scheduled models refresh")
        asyncio.ensure_future(_guarded(aggregator.refresh_models, "models"))

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


async def initial_refresh(aggregator: Aggregator) -> None:
    """Warm the cache once at startup (before the scheduler takes over).

    Both refreshes run concurrently; a slow/failing source can't delay
    startup (each refresh already tolerates SourceError internally).
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
